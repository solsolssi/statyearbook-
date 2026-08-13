from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets

from app.db.connection import DB_PATH, DatabaseConnection, DatabaseRow, connect
from app.db.schema import init_db
from app.models.report import StatTable
from app.models.yearbook_edits import (
    EditableCellPatch,
    EditableColumnPatch,
    EditableHierarchyPatch,
    TableContentUpdateRequest,
    ReportEditAccess,
    StatisticEditAccess,
    TableEditSession,
)
from app.services.database_report_service import DatabaseReportService, base_table_code
from app.core.contact_metadata import PHONE_RE, parse_contact_metadata


PASSWORD_ITERATIONS = 240_000
class YearbookEditError(ValueError):
    pass


class YearbookEditAuthenticationError(YearbookEditError):
    pass


class YearbookEditService:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def get_access(self, report_id: int) -> ReportEditAccess:
        with connect(self._db_path) as connection:
            init_db(connection)
            report = self._require_report(connection, report_id)
            table_groups = report_table_groups(connection, report_id)
            passwords = {
                str(row["table_key"]): row
                for row in connection.execute(
                    """
                    SELECT table_key, is_initial, updated_at
                    FROM yearbook_edit_passwords
                    WHERE report_id = ? AND table_key LIKE 'tables:%'
                    """,
                    (report_id,),
                ).fetchall()
            }
        return ReportEditAccess(
            report_id=report_id,
            year=int(report["year"]),
            title=str(report["title"]),
            statistics=[
                statistic_access(table_id, rows, passwords.get(access_key_for_rows(rows)))
                for table_id, rows in table_groups
            ],
        )

    def set_password(
        self,
        *,
        report_id: int,
        table_id: str,
        new_password: str,
        current_password: str | None,
    ) -> ReportEditAccess:
        with connect(self._db_path) as connection:
            init_db(connection)
            self._require_report(connection, report_id)
            rows = resolve_table_rows(connection, report_id, table_id)
            table_key = access_key_for_rows(rows)
            with connection:
                ensure_initial_password(connection, report_id, rows)
            existing = connection.execute(
                """
                SELECT password_hash, password_salt, password_iterations
                FROM yearbook_edit_passwords
                WHERE report_id = ? AND table_key = ?
                """,
                (report_id, table_key),
            ).fetchone()
            if existing is None or not verify_password(current_password or "", existing):
                raise YearbookEditAuthenticationError("현재 비밀번호가 올바르지 않습니다.")

            salt = secrets.token_bytes(16)
            password_hash = derive_password_hash(new_password, salt, PASSWORD_ITERATIONS)
            with connection:
                connection.execute(
                    """
                    INSERT INTO yearbook_edit_passwords (
                        report_id, table_key, password_hash, password_salt,
                        password_iterations, is_initial, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
                    ON CONFLICT (report_id, table_key) DO UPDATE SET
                        password_hash = excluded.password_hash,
                        password_salt = excluded.password_salt,
                        password_iterations = excluded.password_iterations,
                        is_initial = 0,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        report_id,
                        table_key,
                        password_hash,
                        salt.hex(),
                        PASSWORD_ITERATIONS,
                    ),
                )
                connection.execute(
                    "DELETE FROM yearbook_edit_sessions WHERE report_id = ? AND table_key = ?",
                    (report_id, table_key),
                )
        return self.get_access(report_id)

    def authenticate(
        self,
        *,
        report_id: int,
        table_id: str,
        password: str,
    ) -> TableEditSession:
        with connect(self._db_path) as connection:
            init_db(connection)
            self._require_report(connection, report_id)
            rows = resolve_table_rows(connection, report_id, table_id)
            table_key = access_key_for_rows(rows)
            with connection:
                ensure_initial_password(connection, report_id, rows)
            record = connection.execute(
                """
                SELECT password_hash, password_salt, password_iterations
                FROM yearbook_edit_passwords
                WHERE report_id = ? AND table_key = ?
                """,
                (report_id, table_key),
            ).fetchone()
            if record is None:
                raise YearbookEditAuthenticationError("통계 수정 비밀번호를 준비하지 못했습니다.")
            if not verify_password(password, record):
                raise YearbookEditAuthenticationError("비밀번호가 올바르지 않습니다.")

            token = secrets.token_urlsafe(32)
            token_hash = hash_token(token)
            with connection:
                connection.execute(
                    """
                    INSERT INTO yearbook_edit_sessions (
                        token_hash, report_id, table_key, expires_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (token_hash, report_id, table_key, ""),
                )
        return TableEditSession(access_token=token)

    def update_table(
        self,
        *,
        report_id: int,
        table_id: str,
        access_token: str,
        payload: TableContentUpdateRequest,
    ) -> StatTable:
        token_hash = hash_token(access_token)
        with connect(self._db_path) as connection:
            init_db(connection)
            rows = resolve_table_rows(connection, report_id, table_id)
            table_key = access_key_for_rows(rows)
            self._require_session(connection, report_id, table_key, token_hash)
            row_ids = {int(row["id"]) for row in rows}
            part_ids = {physical_id(part.id) for part in payload.parts}
            if None in part_ids or part_ids != row_ids:
                raise YearbookEditError("수정할 표 구성과 현재 페이지 구성이 일치하지 않습니다.")

            all_report_rows = connection.execute(
                "SELECT id, code FROM stat_tables WHERE report_id = ?",
                (report_id,),
            ).fetchall()
            original_codes = {int(row["id"]): str(row["code"]) for row in all_report_rows}
            target_codes = dict(original_codes)
            hierarchy_scopes = hierarchy_patch_scopes(
                all_report_rows,
                payload.hierarchy_patches,
            )
            # A lower hierarchy number is applied before its parent, so changing
            # both 8-1-3 and 8 in one edit produces the expected 9-1-4 prefix.
            for patch in sorted(payload.hierarchy_patches, key=lambda item: len(item.original_code), reverse=True):
                for row in hierarchy_scopes[patch_key(patch)]:
                    row_id = int(row["id"])
                    target_codes[row_id] = replace_code_prefix(
                        target_codes[row_id], patch.original_code, patch.code.strip()
                    )

            for part in payload.parts:
                part_id = physical_id(part.id)
                assert part_id is not None
                target_codes[part_id] = part.code.strip()

            duplicate_codes = duplicate_target_codes(target_codes)
            if duplicate_codes:
                raise YearbookEditError(f"이미 사용 중인 표 번호입니다: {duplicate_codes[0]}")

            changed_cell_count = sum(
                len(part.columns) + len(part.cells) for part in payload.parts
            )
            latest_run = connection.execute(
                """
                SELECT id FROM validation_runs
                WHERE report_id = ?
                ORDER BY completed_at DESC, id DESC LIMIT 1
                """,
                (report_id,),
            ).fetchone()
            edited_after_run_id = int(latest_run["id"]) if latest_run is not None else 0
            with connection:
                changed_code_ids = [
                    row_id
                    for row_id, code in target_codes.items()
                    if code != original_codes[row_id]
                ]
                # Temporary values avoid transient UNIQUE collisions while a
                # shared hierarchy number is being renamed.
                for row_id in changed_code_ids:
                    connection.execute(
                        "UPDATE stat_tables SET code = ? WHERE id = ? AND report_id = ?",
                        (f"__editing__{row_id}__", row_id, report_id),
                    )
                for patch in payload.hierarchy_patches:
                    scope = hierarchy_scopes[patch_key(patch)]
                    for row in scope:
                        fields = (
                            ("domain = ?", patch.title.strip())
                            if patch.kind == "domain"
                            else (
                                "section_title = ?",
                                "section_title_en = ?",
                            )
                        )
                        values = (
                            [patch.title.strip()]
                            if patch.kind == "domain"
                            else [patch.title.strip(), patch.title_en.strip()]
                        )
                        connection.execute(
                            f"""
                            UPDATE stat_tables
                            SET {', '.join(fields)}, extracted_at = CURRENT_TIMESTAMP,
                                manually_edited_at = CURRENT_TIMESTAMP,
                                edited_after_run_id = ?
                            WHERE id = ? AND report_id = ?
                            """,
                            [*values, edited_after_run_id, int(row["id"]), report_id],
                        )
                for row_id in changed_code_ids:
                    connection.execute(
                        "UPDATE stat_tables SET code = ? WHERE id = ? AND report_id = ?",
                        (target_codes[row_id], row_id, report_id),
                    )
                for part in payload.parts:
                    part_id = physical_id(part.id)
                    assert part_id is not None
                    connection.execute(
                        """
                        UPDATE stat_tables
                        SET code = ?, title = ?, title_en = ?, section_title = ?,
                            section_title_en = ?, domain = ?, unit = ?, base_date = ?,
                            note = ?, source = ?, source_department = ?, source_officer = ?,
                            source_extension = ?, source_reference = ?,
                            extracted_at = CURRENT_TIMESTAMP,
                            manually_edited_at = CURRENT_TIMESTAMP,
                            edited_after_run_id = ?
                        WHERE id = ? AND report_id = ?
                        """,
                        (
                            part.code.strip(),
                            part.title.strip(),
                            part.title_en.strip(),
                            payload.section_title.strip(),
                            payload.section_title_en.strip(),
                            payload.domain.strip(),
                            part.unit.strip(),
                            part.metadata.base_date.strip(),
                            part.metadata.note,
                            part.metadata.source,
                            part.metadata.source_department.strip(),
                            part.metadata.source_officer.strip(),
                            part.metadata.source_extension.strip(),
                            part.metadata.source_reference.strip(),
                            edited_after_run_id,
                            part_id,
                            report_id,
                        ),
                    )
                    for column in part.columns:
                        apply_column_patch(connection, part_id, part.header_count, column)
                    for cell in part.cells:
                        upsert_cell(connection, part_id, cell)

                connection.execute(
                    """
                    INSERT INTO yearbook_manual_edits (
                        report_id, table_key, session_token_hash, changes_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        report_id,
                        table_key,
                        token_hash,
                        json.dumps(
                            {
                                "page_code": payload.code,
                                "page_title": payload.title,
                                "part_ids": sorted(row_ids),
                                "changed_cell_count": changed_cell_count,
                                "hierarchy_patches": [
                                    patch.model_dump() for patch in payload.hierarchy_patches
                                ],
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )

        first_part_id = physical_id(payload.parts[0].id)
        updated_id = (
            f"db-{first_part_id}"
            if len(payload.parts) == 1
            else f"group-{base_table_code(payload.parts[0].code)}"
        )
        updated = DatabaseReportService(self._db_path).get_table(updated_id, report_id)
        if updated is None:
            raise YearbookEditError("수정된 표를 다시 불러오지 못했습니다.")
        return updated

    @staticmethod
    def _require_report(connection: DatabaseConnection, report_id: int) -> DatabaseRow:
        report = connection.execute(
            "SELECT id, year, title FROM annual_reports WHERE id = ?", (report_id,)
        ).fetchone()
        if report is None:
            raise YearbookEditError("연보를 찾을 수 없습니다.")
        return report

    @staticmethod
    def _require_session(
        connection: DatabaseConnection,
        report_id: int,
        table_key: str,
        token_hash: str,
    ) -> None:
        session = connection.execute(
            """
            SELECT 1 FROM yearbook_edit_sessions
            WHERE token_hash = ? AND report_id = ? AND table_key = ?
            """,
            (token_hash, report_id, table_key),
        ).fetchone()
        if session is None:
            raise YearbookEditAuthenticationError(
                "수정 인증이 유효하지 않습니다. 비밀번호를 다시 입력해 주세요."
            )


def resolve_table_rows(
    connection: DatabaseConnection,
    report_id: int,
    table_id: str,
) -> list[DatabaseRow]:
    if connection.execute(
        "SELECT 1 FROM annual_reports WHERE id = ?", (report_id,)
    ).fetchone() is None:
        raise YearbookEditError("연보를 찾을 수 없습니다.")
    if table_id.startswith("db-"):
        raw_id = table_id.removeprefix("db-")
        if not raw_id.isdigit():
            raise YearbookEditError("표 식별자가 올바르지 않습니다.")
        rows = connection.execute(
            "SELECT * FROM stat_tables WHERE report_id = ? AND id = ?",
            (report_id, int(raw_id)),
        ).fetchall()
    else:
        base_code = table_id.removeprefix("group-")
        rows = connection.execute(
            """
            SELECT * FROM stat_tables
            WHERE report_id = ? AND (code = ? OR code LIKE ?)
            ORDER BY table_order, id
            """,
            (report_id, base_code, f"{base_code} 표%"),
        ).fetchall()
    if not rows:
        raise YearbookEditError("표를 찾을 수 없습니다.")
    return rows


def access_key_for_rows(rows: list[DatabaseRow]) -> str:
    return "tables:" + ",".join(str(row["id"]) for row in sorted(rows, key=lambda row: int(row["id"])))


def report_table_groups(
    connection: DatabaseConnection,
    report_id: int,
) -> list[tuple[str, list[DatabaseRow]]]:
    rows = connection.execute(
        """
        SELECT * FROM stat_tables
        WHERE report_id = ?
        ORDER BY table_order, id
        """,
        (report_id,),
    ).fetchall()
    grouped: dict[str, list[DatabaseRow]] = {}
    order: list[str] = []
    for row in rows:
        code = base_table_code(str(row["code"]))
        if code not in grouped:
            grouped[code] = []
            order.append(code)
        grouped[code].append(row)
    return [
        (
            f"db-{group[0]['id']}" if len(group) == 1 else f"group-{code}",
            group,
        )
        for code in order
        if (group := grouped[code])
    ]


def statistic_access(
    table_id: str,
    rows: list[DatabaseRow],
    password: DatabaseRow | None,
) -> StatisticEditAccess:
    first = rows[0]
    officer = next(
        (str(row["source_officer"] or "").strip() for row in rows if str(row["source_officer"] or "").strip()),
        "",
    )
    return StatisticEditAccess(
        table_id=table_id,
        code=base_table_code(str(first["code"])),
        title=re.sub(r"\s+표\s*\d+$", "", str(first["title"])).strip(),
        source_officer=officer,
        has_password=True,
        is_initial_password=bool(password["is_initial"]) if password is not None else True,
        updated_at=str(password["updated_at"] or "") if password is not None else "",
    )


def ensure_initial_password(
    connection: DatabaseConnection,
    report_id: int,
    rows: list[DatabaseRow],
) -> None:
    table_key = access_key_for_rows(rows)
    if connection.execute(
        "SELECT 1 FROM yearbook_edit_passwords WHERE report_id = ? AND table_key = ?",
        (report_id, table_key),
    ).fetchone() is not None:
        return
    password = initial_password_for_rows(rows)
    salt = secrets.token_bytes(16)
    connection.execute(
        """
        INSERT INTO yearbook_edit_passwords (
            report_id, table_key, password_hash, password_salt,
            password_iterations, is_initial
        ) VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT (report_id, table_key) DO NOTHING
        """,
        (
            report_id,
            table_key,
            derive_password_hash(password, salt, PASSWORD_ITERATIONS),
            salt.hex(),
            PASSWORD_ITERATIONS,
        ),
    )


def initial_password_for_rows(rows: list[DatabaseRow]) -> str:
    for row in rows:
        extension = str(row["source_extension"] or "").strip()
        if not extension:
            extension = parse_contact_metadata(str(row["source"] or "")).extension
        match = PHONE_RE.search(extension)
        phone = match.group() if match is not None else extension.split(" / ", 1)[0]
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 4:
            return digits[-4:]
    return "0000"


def hierarchy_patch_scopes(
    rows: list[DatabaseRow],
    patches: list[EditableHierarchyPatch],
) -> dict[tuple[str, str], list[DatabaseRow]]:
    scopes: dict[tuple[str, str], list[DatabaseRow]] = {}
    for patch in patches:
        key = patch_key(patch)
        if key in scopes:
            raise YearbookEditError("같은 대제목을 한 번에 중복 수정할 수 없습니다.")
        scope = [
            row
            for row in rows
            if hierarchy_code_matches(str(row["code"]), patch.original_code)
        ]
        if not scope:
            raise YearbookEditError("변경할 대제목의 표를 찾을 수 없습니다.")
        scopes[key] = scope
    return scopes


def patch_key(patch: EditableHierarchyPatch) -> tuple[str, str]:
    return patch.kind, patch.original_code


def hierarchy_code_matches(code: str, hierarchy_code: str) -> bool:
    base_code = base_table_code(code)
    return base_code == hierarchy_code or base_code.startswith(f"{hierarchy_code}-")


def replace_code_prefix(code: str, old_prefix: str, new_prefix: str) -> str:
    if code == old_prefix:
        return new_prefix
    if code.startswith(f"{old_prefix}-") or code.startswith(f"{old_prefix} 표"):
        return f"{new_prefix}{code[len(old_prefix):]}"
    return code


def duplicate_target_codes(target_codes: dict[int, str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for code in target_codes.values():
        if code in seen and code not in duplicates:
            duplicates.append(code)
        seen.add(code)
    return duplicates


def derive_password_hash(password: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    ).hex()


def verify_password(password: str, record: DatabaseRow) -> bool:
    try:
        salt = bytes.fromhex(str(record["password_salt"]))
        iterations = int(record["password_iterations"])
    except (TypeError, ValueError):
        return False
    candidate = derive_password_hash(password, salt, iterations)
    return hmac.compare_digest(candidate, str(record["password_hash"]))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def physical_id(value: str) -> int | None:
    raw = value.removeprefix("db-")
    return int(raw) if raw.isdigit() else None


def apply_column_patch(
    connection: DatabaseConnection,
    table_id: int,
    header_count: int,
    patch: EditableColumnPatch,
) -> None:
    if header_count <= 0:
        raise YearbookEditError("헤더가 없는 표에서는 헤더 값을 수정할 수 없습니다.")
    source_indexes = sorted(set(patch.source_col_indexes))
    placeholders = ", ".join("?" for _ in source_indexes)
    connection.execute(
        f"""
        UPDATE stat_table_cells
        SET text_value = '', numeric_value = NULL, footnote_marker = ''
        WHERE table_id = ? AND row_index < ? AND col_index IN ({placeholders})
        """,
        [table_id, header_count, *source_indexes],
    )
    value = bilingual_value(patch.label, patch.label_en)
    upsert_raw_cell(
        connection,
        table_id=table_id,
        row_index=header_count - 1,
        col_index=source_indexes[0],
        value=value,
        footnote_marker=patch.footnote_marker,
        is_header=True,
    )


def upsert_cell(
    connection: DatabaseConnection,
    table_id: int,
    patch: EditableCellPatch,
) -> None:
    upsert_raw_cell(
        connection,
        table_id=table_id,
        row_index=patch.row_index,
        col_index=patch.col_index,
        value=bilingual_value(patch.value, patch.value_en),
        footnote_marker=patch.footnote_marker,
        is_header=False,
    )


def upsert_raw_cell(
    connection: DatabaseConnection,
    *,
    table_id: int,
    row_index: int,
    col_index: int,
    value: str,
    footnote_marker: str,
    is_header: bool,
) -> None:
    connection.execute(
        """
        INSERT INTO stat_table_cells (
            table_id, row_index, col_index, text_value, numeric_value,
            is_header, footnote_marker
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (table_id, row_index, col_index) DO UPDATE SET
            text_value = excluded.text_value,
            numeric_value = excluded.numeric_value,
            is_header = excluded.is_header,
            footnote_marker = excluded.footnote_marker
        """,
        (
            table_id,
            row_index,
            col_index,
            value,
            numeric_value(value),
            int(is_header),
            footnote_marker,
        ),
    )


def bilingual_value(value: str, value_en: str) -> str:
    values = [item.strip() for item in (value, value_en) if item.strip()]
    return "\n".join(dict.fromkeys(values))


def numeric_value(value: str) -> float | None:
    cleaned = value.replace(",", "").replace("%", "").strip()
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", cleaned):
        return float(cleaned)
    return None
