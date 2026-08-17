"""Create an editable annual-report draft directly from one increment upload.

The whole statistical ledger is a browse-only reference.  In particular, an
increment must never be merged into it or read it back when producing a new
annual report: the selected predecessor and the three uploaded files are the
only inputs to this workflow.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from difflib import SequenceMatcher
from typing import Any

from app.core.numeric_text import parse_numeric_value
from app.db.connection import DB_PATH, DatabaseConnection, DatabaseRow, connect
from app.db.schema import init_db
from app.yearbook_data.relational_import import (
    DELTA_INFO_COLUMNS,
    DELTA_ITEM_COLUMNS,
    DELTA_VALUE_COLUMNS,
    is_deleted_source_status,
    tabular_rows,
)


MATCHER_VERSION = 5


@dataclass
class IncrementItem:
    data_no: int
    label: str
    full_name: str
    order: int
    data_type: str = ""
    level: int = 0
    item_id: str = ""


@dataclass
class IncrementValue:
    data_no: int
    row_no: int
    value: str


@dataclass
class IncrementDataset:
    key: str
    title: str
    status: str = ""
    management_number: str = ""
    department: str = ""
    reference_time: str = ""
    target_code: str = ""
    publication_order: int = 0
    items: list[IncrementItem] = field(default_factory=list)
    values: list[IncrementValue] = field(default_factory=list)


@dataclass(frozen=True)
class IncrementalDraftResult:
    report_id: int
    datasets: int
    items: int
    values: int
    generated_table_count: int
    review_table_count: int
    deleted_table_count: int
    new_table_count: int
    changed_table_count: int
    unchanged_table_count: int


@dataclass(frozen=True)
class IncrementApplication:
    overlays: dict[tuple[int, int], str]
    message: str
    compatible: bool
    reason_code: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    replacement: "IncrementStructureReplacement | None" = None


@dataclass(frozen=True)
class GeneratedIncrementCell:
    row_index: int
    col_index: int
    value: str
    is_header: bool


@dataclass(frozen=True)
class IncrementStructureReplacement:
    cells: tuple[GeneratedIncrementCell, ...]
    header_count: int
    row_count: int
    column_count: int
    mode: str


@dataclass(frozen=True)
class YearRowAxis:
    column_index: int
    years_by_row: dict[int, int]


@dataclass(frozen=True)
class YearColumnAxis:
    row_index: int
    years_by_column: dict[int, int]


@dataclass(frozen=True)
class MappingCandidate:
    source_key: str
    title: str
    score: float
    title_score: float
    structure_score: float
    metadata_score: float
    number_score: float

    def payload(self) -> dict[str, Any]:
        return {
            "source_key": self.source_key,
            "title": self.title,
            "score": round(self.score, 4),
            "title_score": round(self.title_score, 4),
            "structure_score": round(self.structure_score, 4),
            "metadata_score": round(self.metadata_score, 4),
            "number_score": round(self.number_score, 4),
        }


def unresolved_increment_counts(
    connection: DatabaseConnection,
    report_id: int,
) -> tuple[int, int]:
    """Count disjoint logical blockers that must be resolved before confirm."""
    logical_statuses: dict[str, list[str]] = defaultdict(list)
    for row in connection.execute(
        """
        SELECT table_row.code, status.generation_status
        FROM stat_tables table_row
        LEFT JOIN generated_report_table_status status
          ON status.report_id = table_row.report_id
         AND status.table_id = table_row.id
        WHERE table_row.report_id = ?
        """,
        (report_id,),
    ).fetchall():
        logical_code = re.sub(r"\s+표\s*\d+$", "", str(row["code"] or ""))
        logical_statuses[logical_code].append(str(row["generation_status"] or ""))
    review_count = sum(
        any(status in {"mapping_review", "new_table"} for status in statuses)
        for statuses in logical_statuses.values()
    )
    unmatched_count = int(connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM report_incremental_table_mappings
        WHERE report_id = ? AND match_method = 'new_increment'
        """,
        (report_id,),
    ).fetchone()["count"])
    return review_count, unmatched_count


class IncrementalYearbookService:
    """Keep incremental data scoped to the report draft it updates."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def create_draft(
        self,
        *,
        base_report_id: int,
        target_year: int,
        title: str,
        info_path: Path,
        item_path: Path,
        value_path: Path,
    ) -> IncrementalDraftResult:
        datasets = parse_increment_files(info_path, item_path, value_path)
        source_hash = digest_files([info_path, item_path, value_path])
        imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with connect(self._db_path) as connection:
            init_db(connection)
            base = connection.execute(
                "SELECT * FROM annual_reports WHERE id = ?", (base_report_id,)
            ).fetchone()
            if base is None:
                raise ValueError("기준 연보를 찾을 수 없습니다.")
            if target_year != int(base["year"]) + 1:
                raise ValueError(
                    f"기준 연보 {base['year']}년의 다음 연보는 {int(base['year']) + 1}년으로 생성해야 합니다."
                )
            if connection.execute(
                "SELECT 1 FROM annual_reports WHERE file_hash = ?", (source_hash,)
            ).fetchone():
                raise ValueError("같은 증분 파일로 생성한 연보가 이미 있습니다.")

            with connection:
                cursor = connection.execute(
                    """
                    INSERT INTO annual_reports (
                        year, title, source_file_name, source_file_path, file_hash,
                        parse_warnings_json, imported_at, origin_kind, base_report_id
                    ) VALUES (?, ?, ?, ?, ?, '[]', ?, 'incremental_draft', ?)
                    """,
                    (
                        target_year,
                        title.strip() or f"{target_year} 행정안전통계연보",
                        "증분 업로드 (표정보 · 표항목 · 표데이터)",
                        "incremental://report-scoped-upload",
                        source_hash,
                        imported_at,
                        base_report_id,
                    ),
                )
                report_id = int(cursor.lastrowid)
                connection.execute(
                    """
                    INSERT INTO report_incremental_uploads (
                        report_id, base_report_id, target_year, payload_json, source_hash,
                        matcher_version
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        report_id,
                        base_report_id,
                        target_year,
                        json.dumps(serialize_datasets(datasets), ensure_ascii=False),
                        source_hash,
                        MATCHER_VERSION,
                    ),
                )

                base_rows = connection.execute(
                    "SELECT * FROM stat_tables WHERE report_id = ? ORDER BY table_order, id",
                    (base_report_id,),
                ).fetchall()
                base_mappings = {
                    str(row["table_code"]): str(row["source_key"] or "")
                    for row in connection.execute(
                        """
                        SELECT table_code, source_key
                        FROM report_incremental_table_mappings
                        WHERE report_id = ? AND mapping_status = 'mapped' AND source_key != ''
                        """,
                        (base_report_id,),
                    ).fetchall()
                }
                mappings, matched_keys = choose_mappings(connection, base_rows, base_mappings, datasets)

                changed_tables = 0
                unchanged_tables = 0
                deleted_tables = 0
                review_tables = 0
                copied: list[tuple[DatabaseRow, int, str, int]] = []
                for source_table in base_rows:
                    code = str(source_table["code"])
                    mapping = mappings.get(code)
                    dataset = datasets.get(mapping.source_key) if mapping and mapping.source_key else None
                    if dataset is not None and is_deleted_source_status(dataset.status):
                        deleted_tables += 1
                        self._record_mapping(
                            connection,
                            report_id,
                            code,
                            mapping,
                            "deleted",
                            reason_code="SOURCE_DELETED",
                            evidence={"source_status": dataset.status},
                        )
                        continue
                    target_table_id = copy_table(connection, source_table, report_id=report_id, imported_at=imported_at)
                    application = analyze_increment_application(
                        connection, int(source_table["id"]), dataset,
                    )
                    copy_cells(
                        connection,
                        int(source_table["id"]),
                        target_table_id,
                        {} if application.replacement else application.overlays,
                    )
                    if application.replacement is not None:
                        replace_cells_from_increment(
                            connection,
                            table_id=target_table_id,
                            replacement=application.replacement,
                        )
                    else:
                        record_cell_overlays(
                            connection,
                            report_id=report_id,
                            source_table_id=int(source_table["id"]),
                            target_table_id=target_table_id,
                            source_key=dataset.key if dataset else "",
                            overlays=application.overlays,
                        )
                    if dataset is not None and application.compatible and (
                        application.overlays or application.replacement is not None
                    ):
                        update_table_reference_metadata(connection, target_table_id, dataset)
                    if dataset is not None and application.compatible and (
                        application.overlays or application.replacement is not None
                    ):
                        generation_status = "increment_applied"
                        changed_tables += 1
                    elif dataset is not None and application.compatible and mapping and mapping.mapping_status == "mapped":
                        generation_status = "increment_no_change"
                        unchanged_tables += 1
                    else:
                        generation_status = "mapping_review"
                        review_tables += 1
                    if mapping is None:
                        mapping = MappingDecision("", "", 0, "review")
                    self._record_mapping(
                        connection,
                        report_id,
                        code,
                        mapping,
                        generation_status,
                        reason_code=(
                            application.reason_code if dataset is not None else mapping.reason_code
                        ),
                        evidence={**mapping.evidence, **application.evidence},
                    )
                    connection.execute(
                        """
                        INSERT INTO generated_report_table_status (
                            report_id, table_id, source_table_id, generation_status, generation_message
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            report_id,
                            target_table_id,
                            int(source_table["id"]),
                            generation_status,
                            application.message,
                        ),
                    )
                    copied.append(
                        (
                            source_table,
                            target_table_id,
                            generation_status,
                            application_change_count(application),
                        )
                    )

                apply_target_publication_codes(connection, report_id, datasets)
                new_count = record_unmatched_increment_mappings(
                    connection,
                    report_id=report_id,
                    datasets=datasets,
                    matched_keys=matched_keys,
                )
                review_tables += new_count
                record_update_batch(
                    connection,
                    base_report_id=base_report_id,
                    report_id=report_id,
                    copied=copied,
                    deleted_count=deleted_tables,
                    new_count=new_count,
                )

        return IncrementalDraftResult(
            report_id=report_id,
            datasets=len(datasets),
            items=sum(len(dataset.items) for dataset in datasets.values()),
            values=sum(len(dataset.values) for dataset in datasets.values()),
            generated_table_count=sum(
                status in {"increment_applied", "increment_no_change"}
                for _, _, status, _ in copied
            ),
            review_table_count=review_tables,
            deleted_table_count=deleted_tables,
            new_table_count=new_count,
            changed_table_count=changed_tables,
            unchanged_table_count=unchanged_tables,
        )

    def set_mapping(self, *, report_id: int, table_code: str, source_key: str) -> dict[str, str | int | bool]:
        """Apply a user-confirmed key against only this draft's uploaded data."""
        normalized_key = source_key.strip().upper()
        if not re.fullmatch(r"M[0-9A-Z_-]+", normalized_key):
            raise ValueError("연결 키는 M으로 시작하는 증분 키를 입력해 주세요.")
        with connect(self._db_path) as connection:
            init_db(connection)
            report = connection.execute(
                "SELECT origin_kind FROM annual_reports WHERE id = ?", (report_id,)
            ).fetchone()
            if report is None:
                raise ValueError("연결할 연보를 찾을 수 없습니다.")
            if str(report["origin_kind"] or "") not in {"incremental_draft", "upload_draft"}:
                raise ValueError("연결 키는 연보 생성 초안에서만 수정할 수 있습니다.")
            upload = connection.execute(
                "SELECT payload_json FROM report_incremental_uploads WHERE report_id = ?", (report_id,)
            ).fetchone()
            if upload is None:
                table = connection.execute(
                    "SELECT id FROM stat_tables WHERE report_id = ? AND code = ?", (report_id, table_code)
                ).fetchone()
                if table is None:
                    raise ValueError("연결할 연보 표를 찾을 수 없습니다.")
                with connection:
                    self._record_mapping(
                        connection, report_id, table_code,
                        MappingDecision(
                            normalized_key,
                            "manual_key",
                            1,
                            "mapped",
                            reason_code="MANUAL_KEY_SAVED",
                            evidence={"confirmed_by_user": True},
                        ),
                        "increment_no_change",
                        confirmed_by_user=True,
                    )
                return {
                    "source_key": normalized_key,
                    "applied": False,
                    "applied_cell_count": 0,
                    "message": "연결 키를 저장했습니다. 이후 증분 업로드에서 이 키로 자동 연결합니다.",
                }
            datasets = deserialize_datasets(json.loads(str(upload["payload_json"] or "{}")))
            dataset = datasets.get(normalized_key)
            if dataset is None:
                raise ValueError("이번 증분 업로드에 없는 키입니다.")
            occupied = connection.execute(
                """
                SELECT table_code FROM report_incremental_table_mappings
                WHERE report_id = ? AND source_key = ? AND mapping_status = 'mapped'
                  AND table_code != ? AND match_method != 'new_increment'
                LIMIT 1
                """,
                (report_id, normalized_key, table_code),
            ).fetchone()
            if occupied is not None:
                raise ValueError(
                    f"이 연결 키는 이미 {occupied['table_code']} 통계에 연결되어 있습니다."
                )
            previous_mapping = connection.execute(
                """
                SELECT source_key FROM report_incremental_table_mappings
                WHERE report_id = ? AND table_code = ?
                """,
                (report_id, table_code),
            ).fetchone()
            previous_key = str(previous_mapping["source_key"] or "") if previous_mapping else ""
            table = connection.execute(
                """
                SELECT table_row.*, status.source_table_id
                FROM stat_tables table_row
                LEFT JOIN generated_report_table_status status
                  ON status.report_id = table_row.report_id
                 AND status.table_id = table_row.id
                WHERE table_row.report_id = ? AND table_row.code = ?
                """,
                (report_id, table_code),
            ).fetchone()
            if table is None:
                raise ValueError("연결할 연보 표를 찾을 수 없습니다.")
            with connection:
                restore_increment_overlays(
                    connection,
                    report_id=report_id,
                    table_id=int(table["id"]),
                    source_table_id=(
                        int(table["source_table_id"])
                        if table["source_table_id"] is not None
                        else None
                    ),
                    allow_full_restore=not bool(str(table["manually_edited_at"] or "").strip()),
                )
                application = analyze_increment_application(
                    connection, int(table["id"]), dataset,
                )
                generation_status = (
                    "increment_applied"
                    if application.compatible and (
                        application.overlays or application.replacement is not None
                    )
                    else "increment_no_change"
                    if application.compatible
                    else "mapping_review"
                )
                self._record_mapping(
                    connection,
                    report_id,
                    table_code,
                    MappingDecision(
                        normalized_key,
                        "manual_key",
                        1,
                        "mapped",
                        reason_code=application.reason_code,
                        evidence=application.evidence,
                    ),
                    generation_status,
                    reason_code=application.reason_code,
                    evidence=application.evidence,
                    confirmed_by_user=True,
                )
                if application.replacement is not None:
                    replace_cells_from_increment(
                        connection,
                        table_id=int(table["id"]),
                        replacement=application.replacement,
                    )
                else:
                    base_values = current_cell_values(connection, int(table["id"]))
                    for (row_index, col_index), value in application.overlays.items():
                        connection.execute(
                            """
                            UPDATE stat_table_cells
                            SET text_value = ?, numeric_value = ?
                            WHERE table_id = ? AND row_index = ? AND col_index = ?
                            """,
                            (value, parse_numeric_value(value), int(table["id"]), row_index, col_index),
                        )
                    record_cell_overlays_from_values(
                        connection,
                        report_id=report_id,
                        table_id=int(table["id"]),
                        source_key=normalized_key,
                        base_values=base_values,
                        overlays=application.overlays,
                    )
                if application.compatible and (
                    application.overlays or application.replacement is not None
                ):
                    update_table_reference_metadata(connection, int(table["id"]), dataset)
                mark_table_validation_stale_after_increment(
                    connection,
                    report_id=report_id,
                    table_id=int(table["id"]),
                )
                connection.execute(
                    """
                    INSERT INTO generated_report_table_status (
                        report_id, table_id, source_table_id, generation_status, generation_message
                    ) VALUES (?, ?, NULL, ?, ?)
                    ON CONFLICT(report_id, table_id) DO UPDATE SET
                        generation_status = excluded.generation_status,
                        generation_message = excluded.generation_message
                    """,
                    (
                        report_id,
                        int(table["id"]),
                        generation_status,
                        application.message,
                    ),
                )
                if application.compatible:
                    connection.execute(
                        """
                        DELETE FROM report_incremental_table_mappings
                        WHERE report_id = ? AND table_code = ? AND source_key = ?
                          AND match_method = 'new_increment'
                        """,
                        (report_id, f"미연결-{normalized_key}", normalized_key),
                    )
                    if previous_key and previous_key != normalized_key and previous_key in datasets:
                        record_unmatched_increment_mappings(
                            connection,
                            report_id=report_id,
                            datasets={previous_key: datasets[previous_key]},
                            matched_keys=set(),
                        )
            return {
                "source_key": normalized_key,
                "applied": generation_status == "increment_applied",
                "applied_cell_count": application_change_count(application),
                "message": application.message,
                "reason_code": application.reason_code,
            }

    def preview_mapping(self, *, report_id: int, table_code: str, source_key: str) -> dict[str, Any]:
        normalized_key = source_key.strip().upper()
        if not re.fullmatch(r"M[0-9A-Z_-]+", normalized_key):
            raise ValueError("연결 키는 M으로 시작하는 증분 키를 입력해 주세요.")
        with connect(self._db_path) as connection:
            init_db(connection)
            report = connection.execute(
                "SELECT origin_kind FROM annual_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
            if report is None or str(report["origin_kind"] or "") not in {"incremental_draft", "upload_draft"}:
                raise ValueError("연결 키는 연보 생성 초안에서만 수정할 수 있습니다.")
            upload = connection.execute(
                "SELECT payload_json FROM report_incremental_uploads WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            if upload is None:
                return {
                    "source_key": normalized_key,
                    "compatible": True,
                    "applied_cell_count": 0,
                    "reason_code": "MANUAL_KEY_SAVED",
                    "message": "연결 키를 저장하면 다음 증분 업로드부터 우선 연결합니다.",
                    "evidence": {},
                }
            datasets = deserialize_datasets(json.loads(str(upload["payload_json"] or "{}")))
            dataset = datasets.get(normalized_key)
            if dataset is None:
                raise ValueError("이번 증분 업로드에 없는 키입니다.")
            occupied = connection.execute(
                """
                SELECT table_code FROM report_incremental_table_mappings
                WHERE report_id = ? AND source_key = ? AND mapping_status = 'mapped'
                  AND table_code != ? AND match_method != 'new_increment'
                LIMIT 1
                """,
                (report_id, normalized_key, table_code),
            ).fetchone()
            if occupied is not None:
                raise ValueError(f"이 연결 키는 이미 {occupied['table_code']} 통계에 연결되어 있습니다.")
            table = connection.execute(
                "SELECT id FROM stat_tables WHERE report_id = ? AND code = ?",
                (report_id, table_code),
            ).fetchone()
            if table is None:
                raise ValueError("연결할 연보 표를 찾을 수 없습니다.")
            application = analyze_increment_application(connection, int(table["id"]), dataset)
            return {
                "source_key": normalized_key,
                "title": dataset.title,
                "compatible": application.compatible,
                "applied_cell_count": application_change_count(application),
                "reason_code": application.reason_code,
                "message": application.message,
                "evidence": application.evidence,
            }

    def create_statistic_from_increment(
        self,
        *,
        report_id: int,
        source_key: str,
        table_code: str,
        title: str,
    ) -> dict[str, Any]:
        normalized_key = source_key.strip().upper()
        normalized_code = table_code.strip()
        normalized_title = title.strip()
        if not re.fullmatch(r"M[0-9A-Z_-]+", normalized_key):
            raise ValueError("연결 키는 M으로 시작하는 증분 키여야 합니다.")
        if not normalized_code or not normalized_title:
            raise ValueError("새 통계의 표 번호와 제목을 입력해 주세요.")
        with connect(self._db_path) as connection:
            init_db(connection)
            report = connection.execute(
                "SELECT origin_kind FROM annual_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
            if report is None or str(report["origin_kind"] or "") not in {"incremental_draft", "upload_draft"}:
                raise ValueError("새 통계는 연보 생성 초안에서만 추가할 수 있습니다.")
            upload = connection.execute(
                "SELECT payload_json FROM report_incremental_uploads WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            if upload is None:
                raise ValueError("이 초안에는 새 통계로 만들 증분 업로드가 없습니다.")
            datasets = deserialize_datasets(json.loads(str(upload["payload_json"] or "{}")))
            dataset = datasets.get(normalized_key)
            if dataset is None:
                raise ValueError("이번 증분 업로드에 없는 키입니다.")
            if connection.execute(
                "SELECT 1 FROM stat_tables WHERE report_id = ? AND code = ?",
                (report_id, normalized_code),
            ).fetchone():
                raise ValueError("이미 사용 중인 표 번호입니다.")
            if connection.execute(
                """
                SELECT 1 FROM report_incremental_table_mappings
                WHERE report_id = ? AND source_key = ? AND mapping_status = 'mapped'
                  AND match_method != 'new_increment'
                """,
                (report_id, normalized_key),
            ).fetchone():
                raise ValueError("이미 다른 통계에 연결된 증분 키입니다.")
            active_numbers = {value.data_no for value in dataset.values}
            described_numbers = {item.data_no for item in dataset.items}
            if not active_numbers or active_numbers - described_numbers:
                raise ValueError("표항목 정보가 완전하지 않아 새 통계 구조를 안전하게 만들 수 없습니다.")
            active_items = [item for item in dataset.items if item.data_no in active_numbers]
            application = build_structure_replacement_application(
                cells=[],
                dataset=dataset,
                active_items=active_items,
                trigger="NEW_INCREMENT",
            )
            if application is None or application.replacement is None:
                raise ValueError("증분 항목의 계층이나 자료번호가 중복되어 새 통계를 만들 수 없습니다.")

            with connection:
                max_order = int(connection.execute(
                    "SELECT COALESCE(MAX(table_order), 0) AS value FROM stat_tables WHERE report_id = ?",
                    (report_id,),
                ).fetchone()["value"])
                cursor = connection.execute(
                    """
                    INSERT INTO stat_tables (
                        report_id, code, title, title_en, section_title,
                        section_title_en, domain, unit, base_date, section_file,
                        table_order, cell_range, note, source, extracted_at,
                        raw_context, parse_warnings_json, source_department
                    ) VALUES (?, ?, ?, '', ?, '', '신규 통계', '', ?, '', ?, '', '', '',
                              CURRENT_TIMESTAMP, ?, '[]', ?)
                    """,
                    (
                        report_id,
                        normalized_code,
                        normalized_title,
                        normalized_title,
                        normalized_reference_time(dataset.reference_time),
                        max_order + 1,
                        f"증분 연결 키: {normalized_key}",
                        dataset.department,
                    ),
                )
                table_id = int(cursor.lastrowid)
                replace_cells_from_increment(
                    connection,
                    table_id=table_id,
                    replacement=application.replacement,
                )
                decision = MappingDecision(
                    normalized_key,
                    "manual_new_increment",
                    1,
                    "mapped",
                    reason_code="NEW_INCREMENT_CREATED",
                    evidence={
                        **application.evidence,
                        "confirmed_by_user": True,
                    },
                )
                self._record_mapping(
                    connection,
                    report_id,
                    normalized_code,
                    decision,
                    "increment_applied",
                    reason_code="NEW_INCREMENT_CREATED",
                    evidence=decision.evidence,
                    confirmed_by_user=True,
                )
                connection.execute(
                    """
                    INSERT INTO generated_report_table_status (
                        report_id, table_id, source_table_id,
                        generation_status, generation_message
                    ) VALUES (?, ?, NULL, 'increment_applied', ?)
                    """,
                    (
                        report_id,
                        table_id,
                        f"새 증분 {normalized_key}의 완전한 항목 구조로 통계를 생성했습니다.",
                    ),
                )
                connection.execute(
                    """
                    DELETE FROM report_incremental_table_mappings
                    WHERE report_id = ? AND table_code = ? AND source_key = ?
                      AND match_method = 'new_increment'
                    """,
                    (report_id, f"미연결-{normalized_key}", normalized_key),
                )
            return {
                "table_id": f"db-{table_id}",
                "table_code": normalized_code,
                "title": normalized_title,
                "source_key": normalized_key,
                "created_cell_count": application_change_count(application),
            }

    def keep_existing_table(self, *, report_id: int, table_code: str) -> dict[str, object]:
        """Explicitly resolve a review row without applying an unsafe increment.

        This is intentionally a user action.  Automatic matching must never
        silently turn an incompatible increment into a successful update.
        """
        with connect(self._db_path) as connection:
            init_db(connection)
            report = connection.execute(
                "SELECT origin_kind FROM annual_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
            if report is None or str(report["origin_kind"] or "") != "incremental_draft":
                raise ValueError("기존값 유지는 증분 연보 초안에서만 선택할 수 있습니다.")
            row = connection.execute(
                """
                SELECT mapping.source_key, table_row.id AS table_id,
                       status.generation_status
                FROM stat_tables table_row
                JOIN generated_report_table_status status
                  ON status.report_id = table_row.report_id
                 AND status.table_id = table_row.id
                LEFT JOIN report_incremental_table_mappings mapping
                  ON mapping.report_id = table_row.report_id
                 AND mapping.table_code = table_row.code
                WHERE table_row.report_id = ? AND table_row.code = ?
                """,
                (report_id, table_code),
            ).fetchone()
            if row is None:
                raise ValueError("확인할 기존 통계를 찾을 수 없습니다.")
            if str(row["generation_status"] or "") != "mapping_review":
                raise ValueError("이미 증분 연결 처리가 끝난 통계입니다.")
            source_key = str(row["source_key"] or "")
            message = "증분을 적용하지 않고 이전 연보의 값을 유지하도록 사용자가 확인했습니다."
            with connection:
                connection.execute(
                    """
                    UPDATE report_incremental_table_mappings
                    SET match_method = 'manual_keep_existing',
                        mapping_status = 'mapped',
                        reason_code = 'USER_CONFIRMED_KEEP_EXISTING',
                        confirmed_by_user = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE report_id = ? AND table_code = ?
                    """,
                    (report_id, table_code),
                )
                connection.execute(
                    """
                    UPDATE generated_report_table_status
                    SET generation_status = 'increment_no_change',
                        generation_message = ?
                    WHERE report_id = ? AND table_id = ?
                    """,
                    (message, report_id, int(row["table_id"])),
                )
            return {
                "table_code": table_code,
                "source_key": source_key,
                "resolved": True,
                "message": message,
            }

    def ignore_unmatched_increment(self, *, report_id: int, source_key: str) -> dict[str, object]:
        """Record that a new/unmatched increment is intentionally excluded."""
        normalized_key = source_key.strip().upper()
        with connect(self._db_path) as connection:
            init_db(connection)
            report = connection.execute(
                "SELECT origin_kind FROM annual_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
            if report is None or str(report["origin_kind"] or "") != "incremental_draft":
                raise ValueError("증분 제외는 증분 연보 초안에서만 선택할 수 있습니다.")
            row = connection.execute(
                """
                SELECT table_code FROM report_incremental_table_mappings
                WHERE report_id = ? AND source_key = ? AND match_method = 'new_increment'
                """,
                (report_id, normalized_key),
            ).fetchone()
            if row is None:
                raise ValueError("제외할 미연결 증분을 찾을 수 없습니다.")
            with connection:
                connection.execute(
                    """
                    UPDATE report_incremental_table_mappings
                    SET match_method = 'ignored_increment',
                        mapping_status = 'ignored',
                        reason_code = 'USER_IGNORED_INCREMENT',
                        confirmed_by_user = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE report_id = ? AND source_key = ? AND match_method = 'new_increment'
                    """,
                    (report_id, normalized_key),
                )
            return {
                "source_key": normalized_key,
                "ignored": True,
                "message": "이번 연보에서 제외할 증분으로 기록했습니다.",
            }

    def refresh_automatic_mappings(self, report_id: int | None = None) -> bool:
        """Upgrade an open draft when a safer automatic matcher becomes available.

        Mapping results are saved with a draft, so a draft made before an
        improved matching rule would otherwise remain in the review queue
        forever.  Only untouched ``mapping_review`` rows are reconsidered;
        a user-entered key is never replaced here.
        """
        with connect(self._db_path) as connection:
            init_db(connection)
            report = connection.execute(
                """
                SELECT id, origin_kind, base_report_id
                FROM annual_reports
                WHERE id = ?
                """
                if report_id is not None
                else """
                SELECT id, origin_kind, base_report_id
                FROM annual_reports
                WHERE COALESCE(is_archived, 0) = 0
                  AND COALESCE(origin_kind, 'uploaded') != 'ledger_generated'
                ORDER BY imported_at DESC, id DESC
                LIMIT 1
                """,
                (report_id,) if report_id is not None else (),
            ).fetchone()
            if (
                report is None
                or str(report["origin_kind"] or "") != "incremental_draft"
                or report["base_report_id"] is None
            ):
                return False
            draft_report_id = int(report["id"])
            upload = connection.execute(
                "SELECT payload_json, matcher_version FROM report_incremental_uploads WHERE report_id = ?",
                (draft_report_id,),
            ).fetchone()
            if upload is None:
                return False
            if int(upload["matcher_version"] or 0) >= MATCHER_VERSION:
                return False

            datasets = deserialize_datasets(json.loads(str(upload["payload_json"] or "{}")))
            quarantined = quarantine_unsafe_positional_results(
                connection,
                report_id=draft_report_id,
                datasets=datasets,
            )

            base_report_id = int(report["base_report_id"])
            base_rows = connection.execute(
                "SELECT * FROM stat_tables WHERE report_id = ? ORDER BY table_order, id",
                (base_report_id,),
            ).fetchall()
            base_mappings = {
                str(row["table_code"]): str(row["source_key"] or "")
                for row in connection.execute(
                    """
                    SELECT table_code, source_key
                    FROM report_incremental_table_mappings
                    WHERE report_id = ? AND mapping_status = 'mapped' AND source_key != ''
                    """,
                    (base_report_id,),
                ).fetchall()
            }
            mappings, matched_keys = choose_mappings(connection, base_rows, base_mappings, datasets)
            updated = quarantined > 0
            with connection:
                for source_table in base_rows:
                    base_table_code = str(source_table["code"])
                    mapping = mappings.get(base_table_code)
                    if mapping is None:
                        continue
                    target_table = connection.execute(
                        """
                        SELECT table_row.id, table_row.code, table_row.manually_edited_at,
                               status.source_table_id
                        FROM stat_tables table_row
                        LEFT JOIN generated_report_table_status status
                          ON status.report_id = table_row.report_id
                         AND status.table_id = table_row.id
                        WHERE table_row.report_id = ?
                          AND (status.source_table_id = ? OR table_row.code = ?)
                        ORDER BY CASE WHEN status.source_table_id = ? THEN 0 ELSE 1 END
                        LIMIT 1
                        """,
                        (draft_report_id, int(source_table["id"]), base_table_code, int(source_table["id"])),
                    ).fetchone()
                    if target_table is None:
                        continue
                    table_code = str(target_table["code"] or base_table_code)
                    existing_mapping = connection.execute(
                        """
                        SELECT match_method, source_key FROM report_incremental_table_mappings
                        WHERE report_id = ? AND table_code = ?
                        """,
                        (draft_report_id, table_code),
                    ).fetchone()
                    is_manual = bool(
                        existing_mapping is not None
                        and str(existing_mapping["match_method"] or "") == "manual_key"
                    )
                    if is_manual:
                        continue
                    if str(target_table["manually_edited_at"] or "").strip():
                        self._record_mapping(
                            connection,
                            draft_report_id,
                            table_code,
                            mapping,
                            "mapping_review",
                            reason_code="MANUAL_EDIT_REQUIRES_REVIEW",
                            evidence={**mapping.evidence, "matcher_version": MATCHER_VERSION},
                        )
                        connection.execute(
                            """
                            UPDATE generated_report_table_status
                            SET generation_status = 'mapping_review',
                                generation_message = '사용자가 수정한 표는 자동 재적용하지 않았습니다.'
                            WHERE report_id = ? AND table_id = ?
                            """,
                            (draft_report_id, int(target_table["id"])),
                        )
                        updated = True
                        continue

                    restore_increment_overlays(
                        connection,
                        report_id=draft_report_id,
                        table_id=int(target_table["id"]),
                        source_table_id=(
                            int(target_table["source_table_id"])
                            if target_table["source_table_id"] is not None
                            else None
                        ),
                        allow_full_restore=True,
                    )

                    dataset = datasets.get(mapping.source_key)
                    application = analyze_increment_application(
                        connection, int(target_table["id"]), dataset,
                    )
                    if application.replacement is not None:
                        replace_cells_from_increment(
                            connection,
                            table_id=int(target_table["id"]),
                            replacement=application.replacement,
                        )
                        base_values: dict[tuple[int, int], str] = {}
                    else:
                        base_values = current_cell_values(connection, int(target_table["id"]))
                        for (row_index, col_index), value in application.overlays.items():
                            connection.execute(
                                """
                                UPDATE stat_table_cells
                                SET text_value = ?, numeric_value = ?
                                WHERE table_id = ? AND row_index = ? AND col_index = ?
                                """,
                                (value, parse_numeric_value(value), int(target_table["id"]), row_index, col_index),
                            )
                    generation_status = (
                        "increment_applied"
                        if application.compatible and (
                            application.overlays or application.replacement is not None
                        )
                        else "increment_no_change"
                        if application.compatible
                        else "mapping_review"
                    )
                    self._record_mapping(
                        connection,
                        draft_report_id,
                        table_code,
                        mapping,
                        generation_status,
                        reason_code=(
                            application.reason_code if dataset is not None else mapping.reason_code
                        ),
                        evidence={**mapping.evidence, **application.evidence},
                        confirmed_by_user=is_manual,
                    )
                    if application.replacement is None:
                        record_cell_overlays_from_values(
                            connection,
                            report_id=draft_report_id,
                            table_id=int(target_table["id"]),
                            source_key=dataset.key if dataset else "",
                            base_values=base_values,
                            overlays=application.overlays,
                        )
                    if application.overlays or application.replacement is not None:
                        update_table_reference_metadata(
                            connection,
                            int(target_table["id"]),
                            dataset,
                        )
                        mark_table_validation_stale_after_increment(
                            connection,
                            report_id=draft_report_id,
                            table_id=int(target_table["id"]),
                        )
                    connection.execute(
                        """
                        UPDATE generated_report_table_status
                        SET generation_status = ?, generation_message = ?
                        WHERE report_id = ? AND table_id = ?
                        """,
                        (
                            generation_status,
                            application.message,
                            draft_report_id,
                            int(target_table["id"]),
                        ),
                    )
                    updated = True
                connection.execute(
                    "UPDATE report_incremental_uploads SET matcher_version = ? WHERE report_id = ?",
                    (MATCHER_VERSION, draft_report_id),
                )
                if matched_keys:
                    placeholders = ",".join("?" for _ in matched_keys)
                    connection.execute(
                        f"""
                        DELETE FROM report_incremental_table_mappings
                        WHERE report_id = ? AND match_method = 'new_increment'
                          AND source_key IN ({placeholders})
                        """,
                        (draft_report_id, *sorted(matched_keys)),
                    )
                apply_target_publication_codes(connection, draft_report_id, datasets)
                record_unmatched_increment_mappings(
                    connection,
                    report_id=draft_report_id,
                    datasets=datasets,
                    matched_keys=matched_keys,
                )
            return updated

    def learn_layout_from_reference_report(
        self,
        *,
        report_id: int,
        reference_report_id: int,
    ) -> dict[str, object]:
        """Learn layout behavior by comparing a completed edition.

        The reference is an audit oracle only.  No reference cell value is
        copied into the draft; future updates still consume only the selected
        predecessor and its report-scoped increment upload.
        """
        with connect(self._db_path) as connection:
            init_db(connection)
            draft = connection.execute(
                "SELECT year, origin_kind FROM annual_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
            reference = connection.execute(
                "SELECT year FROM annual_reports WHERE id = ?",
                (reference_report_id,),
            ).fetchone()
            if draft is None or str(draft["origin_kind"] or "") != "incremental_draft":
                raise ValueError("레이아웃을 학습할 증분 초안을 찾을 수 없습니다.")
            if reference is None or int(reference["year"] or 0) != int(draft["year"] or 0):
                raise ValueError("같은 연도의 완성 연보만 비교 기준으로 사용할 수 있습니다.")
            upload = connection.execute(
                "SELECT payload_json FROM report_incremental_uploads WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            if upload is None:
                raise ValueError("증분 업로드 기록을 찾을 수 없습니다.")
            datasets = deserialize_datasets(json.loads(str(upload["payload_json"] or "{}")))
            reference_by_title: dict[str, list[DatabaseRow]] = defaultdict(list)
            for row in connection.execute(
                "SELECT id, code, title, table_order FROM stat_tables WHERE report_id = ?",
                (reference_report_id,),
            ).fetchall():
                reference_by_title[normalized(str(row["title"] or ""))].append(row)

            learned = 0
            compared = 0
            unresolved: list[str] = []
            mapping_rows = connection.execute(
                """
                SELECT mapping.source_key, table_row.id, table_row.code,
                       table_row.title, status.source_table_id
                FROM report_incremental_table_mappings mapping
                JOIN stat_tables table_row
                  ON table_row.report_id = mapping.report_id
                 AND table_row.code = mapping.table_code
                LEFT JOIN generated_report_table_status status
                  ON status.report_id = table_row.report_id
                 AND status.table_id = table_row.id
                WHERE mapping.report_id = ? AND mapping.source_key != ''
                  AND mapping.match_method NOT IN ('new_increment', 'ignored_increment')
                """,
                (report_id,),
            ).fetchall()
            with connection:
                for row in mapping_rows:
                    source_key = str(row["source_key"] or "")
                    dataset = datasets.get(source_key)
                    matches = reference_by_title.get(normalized(str(row["title"] or "")), [])
                    if dataset is None or len(matches) != 1 or row["source_table_id"] is None:
                        unresolved.append(source_key)
                        continue
                    target = matches[0]
                    compared += 1
                    dataset.target_code = str(target["code"] or "")
                    dataset.publication_order = int(target["table_order"] or 0)
                    recipe = infer_increment_recipe_from_tables(
                        connection,
                        source_table_id=int(row["source_table_id"]),
                        reference_table_id=int(target["id"]),
                        dataset=dataset,
                    )
                    if recipe is None:
                        unresolved.append(source_key)
                        continue
                    connection.execute(
                        """
                        INSERT INTO report_incremental_update_recipes (
                            source_key, update_mode, retention_mode, window_size,
                            learned_from_report_id, evidence_json
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(source_key) DO UPDATE SET
                            update_mode = excluded.update_mode,
                            retention_mode = excluded.retention_mode,
                            window_size = excluded.window_size,
                            learned_from_report_id = excluded.learned_from_report_id,
                            evidence_json = excluded.evidence_json,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            source_key,
                            recipe["update_mode"],
                            recipe["retention_mode"],
                            recipe["window_size"],
                            reference_report_id,
                            json.dumps(recipe["evidence"], ensure_ascii=False),
                        ),
                    )
                    learned += 1
                synchronized = synchronize_report_layout_by_title(
                    connection,
                    report_id=report_id,
                    reference_report_id=reference_report_id,
                )
                connection.execute(
                    """
                    UPDATE report_incremental_uploads
                    SET payload_json = ?, matcher_version = 0
                    WHERE report_id = ?
                    """,
                    (json.dumps(serialize_datasets(datasets), ensure_ascii=False), report_id),
                )
            return {
                "compared": compared,
                "learned": learned,
                "renumbered": synchronized,
                "unresolved_keys": sorted(set(unresolved)),
            }

    def audit_against_reference_report(
        self,
        *,
        report_id: int,
        reference_report_id: int,
    ) -> dict[str, object]:
        """Quarantine generated tables that differ from a completed edition."""
        with connect(self._db_path) as connection:
            init_db(connection)
            reference_by_code = {
                str(row["code"]): row
                for row in connection.execute(
                    "SELECT id, code, title FROM stat_tables WHERE report_id = ?",
                    (reference_report_id,),
                ).fetchall()
            }
            reference_by_title: dict[str, list[DatabaseRow]] = defaultdict(list)
            for row in reference_by_code.values():
                reference_by_title[normalized(str(row["title"] or ""))].append(row)
            rows = connection.execute(
                """
                SELECT table_row.id, table_row.code, table_row.title,
                       mapping.source_key, mapping.reason_code
                FROM stat_tables table_row
                JOIN generated_report_table_status status
                  ON status.report_id = table_row.report_id
                 AND status.table_id = table_row.id
                JOIN report_incremental_table_mappings mapping
                  ON mapping.report_id = table_row.report_id
                 AND mapping.table_code = table_row.code
                WHERE table_row.report_id = ?
                  AND status.generation_status = 'increment_applied'
                """,
                (report_id,),
            ).fetchall()
            passed = 0
            failed = 0
            failures: list[dict[str, object]] = []
            with connection:
                for row in rows:
                    target = reference_by_code.get(str(row["code"] or ""))
                    if target is None or normalized(str(target["title"] or "")) != normalized(str(row["title"] or "")):
                        matches = reference_by_title.get(normalized(str(row["title"] or "")), [])
                        target = matches[0] if len(matches) == 1 else None
                    if target is None:
                        reason = "REFERENCE_TABLE_AMBIGUOUS"
                        evidence = {"reference_report_id": reference_report_id}
                    else:
                        draft_matrix = reference_cell_matrix(connection, int(row["id"]))
                        target_matrix = reference_cell_matrix(connection, int(target["id"]))
                        draft_shape = matrix_shape(draft_matrix)
                        target_shape = matrix_shape(target_matrix)
                        differing = sum(
                            draft_matrix.get(coordinate) != target_matrix.get(coordinate)
                            for coordinate in set(draft_matrix) | set(target_matrix)
                        )
                        if draft_shape != target_shape:
                            reason = "REFERENCE_STRUCTURE_MISMATCH"
                        elif differing:
                            reason = "REFERENCE_VALUE_MISMATCH"
                        else:
                            reason = ""
                        evidence = {
                            "reference_report_id": reference_report_id,
                            "reference_table_code": str(target["code"] or ""),
                            "draft_shape": draft_shape,
                            "reference_shape": target_shape,
                            "differing_cells": differing,
                        }
                    if not reason:
                        passed += 1
                        continue
                    failed += 1
                    failures.append({
                        "table_code": str(row["code"] or ""),
                        "title": str(row["title"] or ""),
                        "source_key": str(row["source_key"] or ""),
                        "reason_code": reason,
                        **evidence,
                    })
                    connection.execute(
                        """
                        UPDATE generated_report_table_status
                        SET generation_status = 'mapping_review',
                            generation_message = '실제 완성 연보 대조 결과 구조 또는 값이 일치하지 않습니다.'
                        WHERE report_id = ? AND table_id = ?
                        """,
                        (report_id, int(row["id"])),
                    )
                    connection.execute(
                        """
                        UPDATE report_incremental_table_mappings
                        SET mapping_status = 'review', reason_code = ?, evidence_json = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE report_id = ? AND table_code = ?
                        """,
                        (
                            reason,
                            json.dumps(evidence, ensure_ascii=False),
                            report_id,
                            str(row["code"] or ""),
                        ),
                    )
            return {"passed": passed, "failed": failed, "failures": failures}

    def confirm_draft(self, report_id: int) -> None:
        with connect(self._db_path) as connection:
            init_db(connection)
            report = connection.execute(
                "SELECT origin_kind FROM annual_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
            if report is None:
                raise ValueError("확정할 연보 초안을 찾을 수 없습니다.")
            if str(report["origin_kind"] or "") == "incremental_draft":
                review_count, unmatched_count = unresolved_increment_counts(connection, report_id)
                if review_count or unmatched_count:
                    raise ValueError(
                        "안전하게 반영되지 않은 항목이 남아 있어 확정할 수 없습니다. "
                        f"확인 필요 통계 {review_count}개, 미연결 증분 {unmatched_count}개를 "
                        "증분 연결 화면에서 먼저 처리해 주세요."
                    )
            with connection:
                updated = connection.execute(
                    """
                    UPDATE annual_reports
                    SET origin_kind = CASE origin_kind
                        WHEN 'incremental_draft' THEN 'incremental_confirmed'
                        WHEN 'upload_draft' THEN 'uploaded'
                    END
                    WHERE id = ? AND origin_kind IN ('incremental_draft', 'upload_draft')
                    """,
                    (report_id,),
                ).rowcount
            if not updated:
                raise ValueError("확정할 연보 초안을 찾을 수 없습니다.")

    def list_connections(self, report_id: int) -> dict[str, Any]:
        """Return every connected, uncertain and unmatched increment record."""
        with connect(self._db_path) as connection:
            init_db(connection)
            report = connection.execute(
                "SELECT id, origin_kind FROM annual_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
            if report is None:
                raise ValueError("연보를 찾을 수 없습니다.")
            rows = connection.execute(
                """
                SELECT mapping.table_code, mapping.source_key, mapping.match_method,
                       mapping.confidence, mapping.mapping_status, mapping.reason_code,
                       mapping.evidence_json, mapping.candidates_json,
                       mapping.confirmed_by_user, table_row.id AS table_id,
                       table_row.title, status.generation_status,
                       status.generation_message
                FROM report_incremental_table_mappings mapping
                LEFT JOIN stat_tables table_row
                  ON table_row.report_id = mapping.report_id
                 AND table_row.code = mapping.table_code
                LEFT JOIN generated_report_table_status status
                  ON status.report_id = mapping.report_id
                 AND status.table_id = table_row.id
                WHERE mapping.report_id = ?
                ORDER BY table_row.table_order, mapping.table_code
                """,
                (report_id,),
            ).fetchall()
            connections: list[dict[str, Any]] = []
            unmatched: list[dict[str, Any]] = []
            ignored: list[dict[str, Any]] = []
            for row in rows:
                item = {
                    "table_code": str(row["table_code"] or ""),
                    "table_id": int(row["table_id"]) if row["table_id"] is not None else None,
                    "title": str(row["title"] or ""),
                    "source_key": str(row["source_key"] or ""),
                    "match_method": str(row["match_method"] or ""),
                    "confidence": float(row["confidence"] or 0),
                    "mapping_status": str(row["mapping_status"] or ""),
                    "generation_status": str(row["generation_status"] or ""),
                    "generation_message": str(row["generation_message"] or ""),
                    "reason_code": str(row["reason_code"] or ""),
                    "evidence": safe_json_object(str(row["evidence_json"] or "{}")),
                    "candidates": safe_json_list(str(row["candidates_json"] or "[]")),
                    "confirmed_by_user": bool(row["confirmed_by_user"]),
                }
                if item["match_method"] == "new_increment":
                    unmatched.append(item)
                elif item["match_method"] == "ignored_increment":
                    ignored.append(item)
                else:
                    connections.append(item)
            table_status_rows = connection.execute(
                """
                SELECT table_row.code, status.generation_status
                FROM stat_tables table_row
                LEFT JOIN generated_report_table_status status
                  ON status.report_id = table_row.report_id
                 AND status.table_id = table_row.id
                WHERE table_row.report_id = ?
                """,
                (report_id,),
            ).fetchall()
            logical_statuses: dict[str, list[str]] = defaultdict(list)
            for row in table_status_rows:
                logical_code = re.sub(r"\s+표\s*\d+$", "", str(row["code"] or ""))
                logical_statuses[logical_code].append(str(row["generation_status"] or ""))
            logical_review = sum(
                any(status in {"mapping_review", "new_table"} for status in statuses)
                for statuses in logical_statuses.values()
            )
            logical_total = len(logical_statuses)
            return {
                "report_id": report_id,
                "connections": connections,
                "unmatched_increments": unmatched,
                "ignored_increments": ignored,
                "summary": {
                    "total": logical_total,
                    "connected": logical_total - logical_review,
                    "review": logical_review,
                    "unmatched": len(unmatched),
                    "deleted": sum(item["reason_code"] == "SOURCE_DELETED" for item in connections),
                    "identified_physical_tables": sum(
                        item["mapping_status"] == "mapped" for item in connections
                    ),
                },
            }

    @staticmethod
    def _record_mapping(
        connection: DatabaseConnection,
        report_id: int,
        table_code: str,
        mapping: "MappingDecision",
        generation_status: str,
        *,
        reason_code: str = "",
        evidence: dict[str, Any] | None = None,
        confirmed_by_user: bool = False,
    ) -> None:
        connection.execute(
            """
            INSERT INTO report_incremental_table_mappings (
                report_id, table_code, source_key, match_method, confidence,
                mapping_status, reason_code, evidence_json, candidates_json,
                confirmed_by_user
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_id, table_code) DO UPDATE SET
                source_key = excluded.source_key, match_method = excluded.match_method,
                confidence = excluded.confidence, mapping_status = excluded.mapping_status,
                reason_code = excluded.reason_code,
                evidence_json = excluded.evidence_json,
                candidates_json = excluded.candidates_json,
                confirmed_by_user = excluded.confirmed_by_user,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                report_id,
                table_code,
                mapping.source_key,
                mapping.method,
                mapping.confidence,
                "mapped"
                if generation_status in {"increment_applied", "increment_no_change"}
                else mapping.mapping_status,
                reason_code or mapping.reason_code,
                json.dumps(evidence if evidence is not None else mapping.evidence, ensure_ascii=False),
                json.dumps([candidate.payload() for candidate in mapping.candidates], ensure_ascii=False),
                int(confirmed_by_user),
            ),
        )


@dataclass(frozen=True)
class MappingDecision:
    source_key: str
    method: str
    confidence: float
    mapping_status: str
    reason_code: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    candidates: tuple[MappingCandidate, ...] = ()


def parse_increment_files(info_path: Path, item_path: Path, value_path: Path) -> dict[str, IncrementDataset]:
    info_headers, info_rows = tabular_rows(info_path)
    require_headers(info_headers, DELTA_INFO_COLUMNS, info_path)
    datasets: dict[str, IncrementDataset] = {}
    for row in info_rows:
        key = cell(row, "표id")
        if not key:
            continue
        existing = datasets.get(key)
        candidate = IncrementDataset(
            key=key,
            title=cell(row, "표이름") or key,
            status=cell(row, "입력상태"),
            management_number=cell(row, "작성관리번호"),
            department=cell(row, "담당부서"),
            reference_time=cell(row, "자료시점"),
            target_code=first_cell(
                row,
                "연보표번호",
                "통계표번호",
                "통계번호",
                "표번호",
                "table_code",
            ),
            publication_order=integer(
                first_cell(row, "연보표순서", "표순서", "publication_order"),
                default=0,
            ),
        )
        datasets[key] = candidate if existing is None or is_deleted_source_status(candidate.status) else existing

    item_headers, item_rows = tabular_rows(item_path)
    require_headers(item_headers, DELTA_ITEM_COLUMNS, item_path)
    for row in item_rows:
        dataset = datasets.get(cell(row, "STATBL_ID"))
        if dataset is None:
            continue
        data_no = integer(cell(row, "자료번호"), default=-1)
        if data_no < 0:
            continue
        dataset.items.append(IncrementItem(
            data_no=data_no,
            label=cell(row, "항목명"),
            full_name=cell(row, "전체항목명"),
            order=integer(cell(row, "표시순번"), default=data_no),
            data_type=cell(row, "데이터유형"),
            level=integer(cell(row, "레벨"), default=0),
            item_id=cell(row, "itmId"),
        ))

    value_headers, value_rows = tabular_rows(value_path)
    require_headers(value_headers, DELTA_VALUE_COLUMNS, value_path)
    for row in value_rows:
        dataset = datasets.get(cell(row, "STATBL_ID"))
        if dataset is None:
            continue
        dataset.values.append(IncrementValue(
            data_no=integer(cell(row, "자료번호"), default=-1),
            row_no=integer(cell(row, "데이터행번호"), default=-1),
            value=cell(row, "데이터값"),
        ))
    for dataset in datasets.values():
        dataset.items.sort(key=lambda item: (item.order, item.data_no))
    if datasets and not any(dataset.items for dataset in datasets.values()):
        raise ValueError(
            "표항목 파일에 표정보와 연결되는 항목이 없습니다. "
            "표정보·표항목·표데이터 파일을 각각 올바르게 선택해 주세요."
        )
    return datasets


def choose_mappings(
    connection: DatabaseConnection,
    tables: list[DatabaseRow],
    known_mappings: dict[str, str],
    datasets: dict[str, IncrementDataset],
) -> tuple[dict[str, MappingDecision], set[str]]:
    result: dict[str, MappingDecision] = {}
    matched: set[str] = set()
    table_profiles = {
        str(table["code"]): build_table_profile(connection, table)
        for table in tables
    }
    dataset_profiles = {
        key: build_dataset_profile(dataset) for key, dataset in datasets.items()
    }

    # A key confirmed on the predecessor is the strongest available identity.
    # This is report-scoped history, not a lookup into the global ledger.
    unresolved: list[DatabaseRow] = []
    for table in tables:
        code = str(table["code"])
        known_key = (known_mappings.get(code) or key_from_table(table)).strip().upper()
        if known_key and known_key in datasets:
            candidate = score_mapping_candidate(
                table_profiles[code], datasets[known_key], dataset_profiles[known_key]
            )
            result[code] = MappingDecision(
                known_key,
                "confirmed_source_key",
                1,
                "mapped",
                reason_code="CONFIRMED_KEY",
                evidence={"identity": "predecessor_key"},
                candidates=(candidate,),
            )
            matched.add(known_key)
        else:
            unresolved.append(table)

    ranked: dict[str, list[MappingCandidate]] = {}
    for table in unresolved:
        code = str(table["code"])
        ranked[code] = sorted(
            (
                score_mapping_candidate(
                    table_profiles[code], dataset, dataset_profiles[dataset.key]
                )
                for dataset in datasets.values()
                if dataset.key not in matched and not is_deleted_source_status(dataset.status)
            ),
            key=lambda candidate: candidate.score,
            reverse=True,
        )

    # A fuzzy result must also be the dataset's best table.  This mutual-best
    # guard prevents one plausible increment from being silently reused by
    # several similarly named statistics.
    best_table_by_key: dict[str, tuple[str, float]] = {}
    for code, candidates in ranked.items():
        for candidate in candidates:
            previous = best_table_by_key.get(candidate.source_key)
            if previous is None or candidate.score > previous[1]:
                best_table_by_key[candidate.source_key] = (code, candidate.score)

    title_counts: dict[str, int] = defaultdict(int)
    management_counts: dict[str, int] = defaultdict(int)
    for dataset in datasets.values():
        if normalized(dataset.title):
            title_counts[normalized(dataset.title)] += 1
        if normalized_management_number(dataset.management_number):
            management_counts[normalized_management_number(dataset.management_number)] += 1

    for table in unresolved:
        code = str(table["code"])
        candidates = ranked[code]
        top_candidates = tuple(candidates[:3])
        top = candidates[0] if candidates else None
        runner_score = candidates[1].score if len(candidates) > 1 else 0.0
        profile = table_profiles[code]
        if top is None:
            result[code] = MappingDecision(
                "", "", 0, "review", reason_code="NO_INCREMENT_CANDIDATE"
            )
            continue

        dataset = datasets[top.source_key]
        title_exact = bool(profile["title"] and profile["title"] == normalized(dataset.title))
        management_exact = bool(
            profile["management_number"]
            and profile["management_number"] == normalized_management_number(dataset.management_number)
        )
        mutual_best = best_table_by_key.get(top.source_key, ("", 0))[0] == code
        margin = top.score - runner_score
        method = ""
        confidence = top.score
        if management_exact and management_counts[profile["management_number"]] == 1 and mutual_best:
            method = "exact_management_number"
            confidence = 0.995
        elif title_exact and title_counts[profile["title"]] == 1 and mutual_best:
            method = "exact_title"
            confidence = 0.98
        elif top.score >= 0.82 and margin >= 0.08 and mutual_best:
            method = "title_number_metadata_structure"

        evidence = {
            "margin": round(margin, 4),
            "mutual_best": mutual_best,
            "table_shape": profile["shape"],
        }
        if method:
            result[code] = MappingDecision(
                top.source_key,
                method,
                confidence,
                "mapped",
                reason_code="AUTO_IDENTITY_MATCH",
                evidence=evidence,
                candidates=top_candidates,
            )
            matched.add(top.source_key)
        else:
            reason = (
                "AMBIGUOUS_CANDIDATE"
                if top.score >= 0.65
                else "NO_RELIABLE_CANDIDATE"
            )
            result[code] = MappingDecision(
                "",
                "candidate_review",
                top.score,
                "review",
                reason_code=reason,
                evidence=evidence,
                candidates=top_candidates,
            )
    return result, matched


def build_table_profile(connection: DatabaseConnection, table: DatabaseRow) -> dict[str, Any]:
    cells = connection.execute(
        """
        SELECT row_index, col_index, text_value, is_header
        FROM stat_table_cells WHERE table_id = ? ORDER BY row_index, col_index
        """,
        (int(table["id"]),),
    ).fetchall()
    header_paths = table_header_paths(cells)
    body_rows = sorted({int(row["row_index"]) for row in cells if not bool(row["is_header"])})
    columns = sorted({int(row["col_index"]) for row in cells})
    metadata = " ".join(
        str(table[field] or "") for field in ("source", "domain", "section_title")
    )
    return {
        "code": str(table["code"] or ""),
        "title": normalized(str(table["title"] or "")),
        "metadata": normalized(metadata),
        "management_number": management_number_from_table(table),
        "header_paths": header_paths,
        "shape": {"rows": len(body_rows), "columns": len(columns)},
    }


def build_dataset_profile(dataset: IncrementDataset) -> dict[str, Any]:
    active_numbers = {value.data_no for value in dataset.values}
    active_items = [item for item in dataset.items if item.data_no in active_numbers]
    values_by_row: dict[int, set[int]] = defaultdict(set)
    for value in dataset.values:
        values_by_row[value.row_no].add(value.data_no)
    return {
        "title": normalized(dataset.title),
        "department": normalized(dataset.department),
        "management_number": normalized_management_number(dataset.management_number),
        "active_item_paths": [
            (normalized(item.full_name or item.label), normalized(item.label))
            for item in active_items
        ],
        "source_rows": len(values_by_row),
        "source_columns": max((len(values) for values in values_by_row.values()), default=0),
    }


def score_mapping_candidate(
    profile: dict[str, Any],
    dataset: IncrementDataset,
    dataset_profile: dict[str, Any] | None = None,
) -> MappingCandidate:
    dataset_profile = dataset_profile or build_dataset_profile(dataset)
    title_score = SequenceMatcher(None, profile["title"], dataset_profile["title"]).ratio()
    metadata_score = (
        SequenceMatcher(None, profile["metadata"], dataset_profile["department"]).ratio()
        if profile["metadata"] and dataset_profile["department"]
        else 0.0
    )
    number_score = candidate_number_score(profile, dataset, dataset_profile)
    structure_score = candidate_structure_score(profile, dataset_profile)
    score = title_score * 0.48 + structure_score * 0.34 + metadata_score * 0.10 + number_score * 0.08
    return MappingCandidate(
        source_key=dataset.key,
        title=dataset.title,
        score=score,
        title_score=title_score,
        structure_score=structure_score,
        metadata_score=metadata_score,
        number_score=number_score,
    )


def similarity_score(connection: DatabaseConnection, table: DatabaseRow, dataset: IncrementDataset) -> float:
    """Compatibility wrapper kept for callers and focused unit tests."""
    return score_mapping_candidate(build_table_profile(connection, table), dataset).score


def table_header_text(connection: DatabaseConnection, table_id: int) -> list[str]:
    return [
        str(row["text_value"] or "")
        for row in connection.execute(
            """SELECT text_value FROM stat_table_cells
               WHERE table_id = ? AND is_header = 1
               ORDER BY row_index, col_index""",
            (table_id,),
        ).fetchall()
    ]


def table_header_paths(cells: list[DatabaseRow]) -> dict[int, tuple[str, ...]]:
    header_rows = sorted({int(row["row_index"]) for row in cells if bool(row["is_header"])})
    columns = sorted({int(row["col_index"]) for row in cells})
    raw_by_coordinate = {
        (int(row["row_index"]), int(row["col_index"])): display_header_text(str(row["text_value"] or ""))
        for row in cells
        if bool(row["is_header"])
    }
    by_coordinate: dict[tuple[int, int], str] = {}
    for row_index in header_rows:
        inherited = ""
        for column in columns:
            value = raw_by_coordinate.get((row_index, column), "")
            if value:
                inherited = value
            by_coordinate[(row_index, column)] = value or inherited
    paths: dict[int, tuple[str, ...]] = {}
    for column in columns:
        parts: list[str] = []
        for row_index in header_rows:
            value = by_coordinate.get((row_index, column), "")
            if value and (not parts or normalized(parts[-1]) != normalized(value)):
                parts.append(value)
        paths[column] = tuple(parts)
    return paths


def display_header_text(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return ""
    korean = [line for line in lines if re.search(r"[가-힣]", line)]
    return " ".join(korean) if korean else lines[0]


def normalized_management_number(value: str) -> str:
    cleaned = value.strip()
    if re.fullmatch(r"\d+\.0", cleaned):
        cleaned = cleaned[:-2]
    return re.sub(r"[^0-9A-Za-z]", "", cleaned).lower()


def management_number_from_table(table: DatabaseRow) -> str:
    source = " ".join(str(table[field] or "") for field in ("source", "raw_context"))
    patterns = (
        r"(?:작성\s*관리\s*번호|관리\s*번호)\s*[:#]?\s*([0-9A-Za-z.-]+)",
        r"(?:management\s*(?:no|number))\s*[:#]?\s*([0-9A-Za-z.-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, source, re.I)
        if match:
            return normalized_management_number(match.group(1))
    return ""


def candidate_number_score(
    profile: dict[str, Any],
    dataset: IncrementDataset,
    dataset_profile: dict[str, Any] | None = None,
) -> float:
    dataset_profile = dataset_profile or build_dataset_profile(dataset)
    management = dataset_profile["management_number"]
    if profile["management_number"] and management:
        return 1.0 if profile["management_number"] == management else 0.0
    code = normalized(str(profile["code"]))
    return 1.0 if code and code in normalized(dataset.title) else 0.0


def candidate_structure_score(profile: dict[str, Any], dataset_profile: dict[str, Any]) -> float:
    existing_paths = {
        normalized(">".join(path))
        for path in profile["header_paths"].values()
        if path
    }
    existing_leaves = {
        normalized(path[-1])
        for path in profile["header_paths"].values()
        if path
    }
    semantic_matches = sum(
        path in existing_paths or leaf in existing_leaves
        for path, leaf in dataset_profile["active_item_paths"]
    )
    active_item_count = len(dataset_profile["active_item_paths"])
    semantic_score = semantic_matches / active_item_count if active_item_count else 0.0

    source_columns = int(dataset_profile["source_columns"])
    source_rows = int(dataset_profile["source_rows"])
    target_columns = int(profile["shape"]["columns"])
    target_rows = int(profile["shape"]["rows"])
    column_score = 1.0 if source_columns in {target_columns, max(0, target_columns - 1)} else 0.0
    row_score = 1.0 if source_rows in {1, target_rows} else min(source_rows, target_rows) / max(source_rows, target_rows, 1)
    shape_score = column_score * 0.7 + row_score * 0.3
    if active_item_count:
        return semantic_score * 0.8 + shape_score * 0.2
    # Shape alone is supporting evidence, never enough to prove identity.
    return shape_score * 0.35


def key_from_table(table: DatabaseRow) -> str:
    source = " ".join(str(table[field] or "") for field in ("source", "raw_context"))
    match = re.search(r"(?:원장\s*(?:번호|id)|표\s*id|statbl[_\s-]*id)\s*[:#]?\s*([A-Za-z0-9_-]+)", source, re.I)
    return match.group(1).strip() if match else ""


def apply_increment_to_table(
    connection: DatabaseConnection, table_id: int, dataset: IncrementDataset | None,
) -> tuple[dict[tuple[int, int], str], str, bool]:
    """Backward-compatible tuple API for older callers and tests."""
    result = analyze_increment_application(connection, table_id, dataset)
    return result.overlays, result.message, result.compatible


def analyze_increment_application(
    connection: DatabaseConnection,
    table_id: int,
    dataset: IncrementDataset | None,
) -> IncrementApplication:
    if dataset is None:
        return IncrementApplication(
            {},
            "증분 파일에서 신뢰할 수 있는 연결 후보를 찾지 못했습니다. 후보 근거를 확인하거나 M 연결 키를 직접 입력해 주세요.",
            False,
            "NO_RELIABLE_CANDIDATE",
        )
    cells = connection.execute(
        "SELECT row_index, col_index, text_value, is_header FROM stat_table_cells WHERE table_id = ? ORDER BY row_index, col_index",
        (table_id,),
    ).fetchall()
    if not cells:
        return IncrementApplication(
            {},
            f"연결 키 {dataset.key}는 확인했지만 대상 표에 셀이 없습니다.",
            False,
            "EMPTY_TARGET_TABLE",
        )
    header_rows = {int(row["row_index"]) for row in cells if bool(row["is_header"])}
    header_paths = table_header_paths(cells)
    values_by_item: dict[int, list[IncrementValue]] = defaultdict(list)
    for value in dataset.values:
        values_by_item[value.data_no].append(value)
    body_rows = sorted({int(row["row_index"]) for row in cells if int(row["row_index"]) not in header_rows})
    if not dataset.items:
        return IncrementApplication(
            {},
            f"연결 키 {dataset.key}는 확인했지만 표항목 정보가 없어 자료번호와 기존 열의 의미를 "
            "검증할 수 없습니다. 표항목 파일을 보완하거나 열 연결을 직접 확인해 주세요.",
            False,
            "MISSING_ITEM_METADATA",
            {
                "target_rows": len(body_rows),
                "target_columns": len(header_paths),
                "source_rows": len({value.row_no for value in dataset.values}),
                "source_columns": len({value.data_no for value in dataset.values}),
            },
        )
    active_item_numbers = {value.data_no for value in dataset.values}
    if not active_item_numbers:
        return IncrementApplication(
            {},
            f"연결 키 {dataset.key}에는 목표 연도에 반영할 값이 없습니다.",
            False,
            "NO_TARGET_VALUES",
        )
    described_item_numbers = {item.data_no for item in dataset.items}
    missing_descriptions = active_item_numbers - described_item_numbers
    if missing_descriptions:
        return IncrementApplication(
            {},
            f"연결 키 {dataset.key}의 값 {len(missing_descriptions)}개는 표항목 설명이 없어 자동 반영하지 않았습니다.",
            False,
            "UNDESCRIBED_VALUE_ITEMS",
            {"data_numbers": sorted(missing_descriptions)},
        )

    active_items = [item for item in dataset.items if item.data_no in active_item_numbers]
    update_recipe = increment_update_recipe(connection, dataset.key)
    retention_mode = str(update_recipe.get("retention_mode") or "rolling_window")
    column_mapping, unresolved = match_increment_items_to_columns(active_items, header_paths)
    source_rows = sorted({value.row_no for value in dataset.values})
    year_axis = detect_year_row_axis(cells, body_rows)
    year_column_axis = detect_year_column_axis(cells)
    if (
        len(source_rows) == 1
        and (year_axis is not None or year_column_axis is not None)
        and target_reference_year(dataset) is None
    ):
        return IncrementApplication(
            {},
            f"연결 키 {dataset.key}의 기준연도 값이 없어 연도표에 새 행을 추가할 수 없습니다.",
            False,
            "TARGET_YEAR_MISSING",
            {"row_match_method": "year_axis", "target_rows": len(body_rows)},
        )
    if len(source_rows) == 1 and year_axis is None and year_column_axis is not None:
        return build_time_column_application(
            cells=cells,
            dataset=dataset,
            active_items=active_items,
            year_axis=year_column_axis,
            retention_mode=retention_mode,
        )
    if unresolved:
        if len(source_rows) == 1 and year_axis is not None:
            rows_per_year = Counter(year_axis.years_by_row.values())
            if max(rows_per_year.values(), default=0) > 1:
                grouped = build_grouped_time_row_application(
                    cells=cells,
                    dataset=dataset,
                    active_items=active_items,
                    year_axis=year_axis,
                    retention_mode=retention_mode,
                )
                if grouped is not None:
                    return grouped
        rebuilt = build_structure_replacement_application(
            cells=cells,
            dataset=dataset,
            active_items=active_items,
            trigger="HEADER_STRUCTURE_MISMATCH",
            retention_mode=retention_mode,
        )
        if rebuilt is not None:
            return rebuilt
        return IncrementApplication(
            {},
            f"연결 키 {dataset.key}는 확인했지만 값이 있는 항목 {len(unresolved)}개의 헤더 경로가 기존 표와 다릅니다.",
            False,
            "HEADER_STRUCTURE_MISMATCH",
            {
                "unresolved_items": [
                    {"data_no": item.data_no, "label": item.label, "full_name": item.full_name}
                    for item in unresolved
                ],
                "target_headers": [">".join(path) for path in header_paths.values()],
            },
        )

    if len(source_rows) == 1 and year_axis is not None:
        return build_time_series_application(
            cells=cells,
            dataset=dataset,
            active_items=active_items,
            column_mapping=column_mapping,
            year_axis=year_axis,
            retention_mode=retention_mode,
        )
    row_mapping, row_reason, row_evidence = match_increment_rows(
        cells=cells,
        body_rows=body_rows,
        source_rows=source_rows,
        values_by_item=values_by_item,
        column_mapping=column_mapping,
        active_items=active_items,
    )
    if row_mapping is None:
        rebuilt = build_structure_replacement_application(
            cells=cells,
            dataset=dataset,
            active_items=active_items,
            trigger=row_reason,
            retention_mode=retention_mode,
        )
        if rebuilt is not None:
            return rebuilt
        return IncrementApplication(
            {},
            f"연결 키 {dataset.key}는 확인했지만 행 구조가 기존 표와 달라 자동 반영하지 않았습니다.",
            False,
            row_reason,
            row_evidence,
        )

    overlays: dict[tuple[int, int], str] = {}
    for item in active_items:
        column = column_mapping[item.data_no]
        for value in values_by_item[item.data_no]:
            target_row = row_mapping.get(value.row_no)
            if target_row is not None:
                overlays[(target_row, column)] = value.value
    return IncrementApplication(
        overlays,
        f"증분 키 {dataset.key}의 항목 {len(column_mapping)}개, 셀 {len(overlays)}개를 구조 검증 후 반영했습니다.",
        True,
        "STRUCTURE_VERIFIED",
        {
            "matched_columns": len(column_mapping),
            "matched_rows": len(row_mapping),
            "applied_cells": len(overlays),
            **row_evidence,
        },
    )


def match_increment_items_to_columns(
    items: list[IncrementItem],
    header_paths: dict[int, tuple[str, ...]],
) -> tuple[dict[int, int], list[IncrementItem]]:
    candidates: list[tuple[float, int, int]] = []
    for item in items:
        item_path = normalized(item.full_name or item.label)
        item_leaf = normalized(item.label or (item.full_name.split(">")[-1] if item.full_name else ""))
        for column, path in header_paths.items():
            path_key = normalized(">".join(path))
            leaf_key = normalized(path[-1]) if path else ""
            full_score = SequenceMatcher(None, item_path, path_key).ratio() if item_path and path_key else 0.0
            leaf_score = SequenceMatcher(None, item_leaf, leaf_key).ratio() if item_leaf and leaf_key else 0.0
            score = max(
                1.0 if item_path and item_path == path_key else 0.0,
                0.94 if item_leaf and item_leaf == leaf_key else 0.0,
                0.90 if item_leaf and item_leaf in path_key else 0.0,
                full_score * 0.8 + leaf_score * 0.2,
            )
            candidates.append((score, item.data_no, column))

    mapping: dict[int, int] = {}
    used_columns: set[int] = set()
    for score, data_no, column in sorted(candidates, reverse=True):
        if score < 0.86 or data_no in mapping or column in used_columns:
            continue
        mapping[data_no] = column
        used_columns.add(column)
    unresolved = [item for item in items if item.data_no not in mapping]
    return mapping, unresolved


def match_increment_rows(
    *,
    cells: list[DatabaseRow],
    body_rows: list[int],
    source_rows: list[int],
    values_by_item: dict[int, list[IncrementValue]],
    column_mapping: dict[int, int],
    active_items: list[IncrementItem],
) -> tuple[dict[int, int] | None, str, dict[str, Any]]:
    if not body_rows:
        return None, "EMPTY_TARGET_BODY", {"source_rows": len(source_rows), "target_rows": 0}
    text_by_coordinate = {
        (int(cell["row_index"]), int(cell["col_index"])): str(cell["text_value"] or "")
        for cell in cells
    }
    label_items = [
        item
        for item in active_items
        if column_mapping.get(item.data_no) == min(column_mapping.values(), default=-1)
    ]
    if label_items:
        label_item = label_items[0]
        target_column = column_mapping[label_item.data_no]
        target_by_label = {
            normalized(text_by_coordinate.get((row, target_column), "")): row
            for row in body_rows
            if normalized(text_by_coordinate.get((row, target_column), ""))
        }
        source_values = {
            value.row_no: normalized(value.value)
            for value in values_by_item[label_item.data_no]
            if normalized(value.value)
        }
        textual_labels = {
            source_row: label
            for source_row, label in source_values.items()
            if is_dimension_label(label)
        }
        label_mapping = {
            source_row: target_by_label[label]
            for source_row, label in source_values.items()
            if label in target_by_label
        }
        if len(label_mapping) != len(source_rows):
            for source_row, label in source_values.items():
                if source_row in label_mapping:
                    continue
                compatible_targets = [
                    target_row
                    for target_label, target_row in target_by_label.items()
                    if label and (label in target_label or target_label in label)
                ]
                if len(compatible_targets) == 1:
                    label_mapping[source_row] = compatible_targets[0]
        if len(label_mapping) == len(source_rows):
            return label_mapping, "", {"row_match_method": "label", "matched_labels": len(label_mapping)}
        if len(textual_labels) >= max(1, len(source_rows) // 2):
            return None, "ROW_LABEL_MISMATCH", {
                "source_rows": len(source_rows),
                "target_rows": len(body_rows),
                "unmatched_labels": [
                    label for source_row, label in textual_labels.items() if source_row not in label_mapping
                ][:20],
            }

    if len(source_rows) == 1 and len(body_rows) == 1:
        return {source_rows[0]: body_rows[0]}, "", {"row_match_method": "snapshot_single_row"}

    if len(source_rows) == len(body_rows):
        return dict(zip(source_rows, body_rows)), "", {"row_match_method": "position_exact"}
    return None, "ROW_STRUCTURE_MISMATCH", {
        "source_rows": len(source_rows),
        "target_rows": len(body_rows),
    }


def is_dimension_label(value: str) -> bool:
    if not value:
        return False
    if re.fullmatch(r"(?:19|20)\d{2}", value):
        return True
    return parse_numeric_value(value) is None


def target_reference_year(dataset: IncrementDataset) -> int | None:
    match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", dataset.reference_time or "")
    return int(match.group(1)) if match else None


def increment_update_recipe(
    connection: DatabaseConnection,
    source_key: str,
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT update_mode, retention_mode, window_size, evidence_json
        FROM report_incremental_update_recipes
        WHERE source_key = ?
        """,
        (source_key,),
    ).fetchone()
    if row is None:
        return {}
    return {
        "update_mode": str(row["update_mode"] or ""),
        "retention_mode": str(row["retention_mode"] or ""),
        "window_size": int(row["window_size"] or 0),
        "evidence": safe_json_object(str(row["evidence_json"] or "{}")),
    }


def year_from_cell(value: str) -> int | None:
    match = re.match(r"\s*((?:19|20)\d{2})(?:\s*년)?(?:\D.*)?$", value or "")
    return int(match.group(1)) if match else None


def detect_year_row_axis(
    cells: list[DatabaseRow],
    body_rows: list[int],
) -> YearRowAxis | None:
    if not body_rows:
        return None
    columns = sorted({int(cell["col_index"]) for cell in cells})
    values = {
        (int(cell["row_index"]), int(cell["col_index"])): str(cell["text_value"] or "")
        for cell in cells
    }
    header_paths = table_header_paths(cells)
    best: tuple[float, int, dict[int, int]] | None = None
    for column in columns:
        years = {
            row: year
            for row in body_rows
            if (year := year_from_cell(values.get((row, column), ""))) is not None
        }
        if not years:
            continue
        header = normalized(">".join(header_paths.get(column, ())))
        header_is_year = "연도" in header or "year" in header
        ratio = len(years) / max(1, len(body_rows))
        if len(years) < 2 and not header_is_year:
            continue
        if ratio < 0.5 and not header_is_year:
            continue
        score = ratio + (0.5 if header_is_year else 0)
        if best is None or score > best[0]:
            best = (score, column, years)
    if best is None:
        return None
    column = best[1]
    explicit_years = best[2]
    expanded: dict[int, int] = {}
    current_year: int | None = None
    for row in sorted(body_rows):
        if row in explicit_years:
            current_year = explicit_years[row]
        if current_year is not None:
            expanded[row] = current_year
    return YearRowAxis(column, expanded)


def detect_year_column_axis(cells: list[DatabaseRow]) -> YearColumnAxis | None:
    header_rows = sorted({int(cell["row_index"]) for cell in cells if bool(cell["is_header"])})
    if not header_rows:
        return None
    values = {
        (int(cell["row_index"]), int(cell["col_index"])): str(cell["text_value"] or "")
        for cell in cells
    }
    columns = sorted({int(cell["col_index"]) for cell in cells})
    best: tuple[int, int, dict[int, int]] | None = None
    for row_index in header_rows:
        years = {
            column: year
            for column in columns
            if (year := year_from_cell(values.get((row_index, column), ""))) is not None
        }
        if len(years) < 2:
            continue
        candidate = (len(years), row_index, years)
        if best is None or candidate[0] > best[0]:
            best = candidate
    return YearColumnAxis(best[1], best[2]) if best else None


def build_time_column_application(
    *,
    cells: list[DatabaseRow],
    dataset: IncrementDataset,
    active_items: list[IncrementItem],
    year_axis: YearColumnAxis,
    retention_mode: str,
) -> IncrementApplication:
    target_year = target_reference_year(dataset)
    if target_year is None:
        return IncrementApplication({}, "증분 기준연도가 없습니다.", False, "TARGET_YEAR_MISSING")
    source_rows = sorted({value.row_no for value in dataset.values})
    if len(source_rows) != 1:
        return IncrementApplication({}, "연도 열 증분 행이 한 개가 아닙니다.", False, "YEAR_ROW_COUNT_MISMATCH")
    source_row = source_rows[0]
    values_by_item = {
        value.data_no: value.value
        for value in dataset.values
        if value.row_no == source_row
    }
    header_rows = sorted({int(cell["row_index"]) for cell in cells if bool(cell["is_header"])})
    body_rows = sorted({int(cell["row_index"]) for cell in cells if not bool(cell["is_header"])})
    columns = sorted({int(cell["col_index"]) for cell in cells})
    values = {
        (int(cell["row_index"]), int(cell["col_index"])): str(cell["text_value"] or "")
        for cell in cells
    }
    descriptor_columns = [column for column in columns if column not in year_axis.years_by_column]
    row_labels = {
        row: normalized(" ".join(
            display_header_text(values.get((row, column), ""))
            for column in descriptor_columns
            if values.get((row, column), "").strip()
        ))
        for row in body_rows
    }
    candidates: list[tuple[float, int, int]] = []
    for item in active_items:
        item_label = normalized(item.label or increment_item_path(item)[-1])
        item_path = normalized(" ".join(increment_item_path(item)))
        for row, row_label in row_labels.items():
            if item_label and item_label == row_label:
                score = 1.0
            elif item_label and (item_label in row_label or row_label in item_label):
                score = 0.94
            else:
                score = max(
                    SequenceMatcher(None, item_label, row_label).ratio(),
                    SequenceMatcher(None, item_path, row_label).ratio(),
                )
            candidates.append((score, item.data_no, row))
    row_mapping: dict[int, int] = {}
    used_rows: set[int] = set()
    for score, data_no, row in sorted(candidates, reverse=True):
        if score < 0.72 or data_no in row_mapping or row in used_rows:
            continue
        row_mapping[data_no] = row
        used_rows.add(row)
    unresolved = [item for item in active_items if item.data_no not in row_mapping]
    if unresolved:
        return IncrementApplication(
            {},
            f"증분 항목 {len(unresolved)}개를 연도 열 표의 행과 안전하게 연결하지 못했습니다.",
            False,
            "YEAR_COLUMN_ROW_MISMATCH",
            {
                "update_mode": "time_columns",
                "target_year": target_year,
                "unresolved_items": [item.label for item in unresolved[:20]],
            },
        )

    existing_target = next(
        (column for column, year in year_axis.years_by_column.items() if year == target_year),
        None,
    )
    if existing_target is None and target_year <= max(year_axis.years_by_column.values()):
        return IncrementApplication(
            {},
            "증분 기준연도가 표의 마지막 연도보다 새롭지 않습니다.",
            False,
            "YEAR_SEQUENCE_CONFLICT",
            {"target_year": target_year, "latest_year": max(year_axis.years_by_column.values())},
        )
    removed_year: int | None = None
    removed_column: int | None = None
    if existing_target is None and retention_mode == "rolling_window":
        removed_year = min(year_axis.years_by_column.values())
        removed_column = min(
            column for column, year in year_axis.years_by_column.items() if year == removed_year
        )
    kept_columns = [column for column in columns if column != removed_column]
    generated: list[GeneratedIncrementCell] = []
    column_remap = {old_column: index for index, old_column in enumerate(kept_columns)}
    for new_row, old_row in enumerate(header_rows):
        for old_column in kept_columns:
            generated.append(GeneratedIncrementCell(
                new_row,
                column_remap[old_column],
                values.get((old_row, old_column), ""),
                True,
            ))
    if existing_target is None:
        target_column = len(kept_columns)
        for new_row, old_row in enumerate(header_rows):
            value = str(target_year) if old_row == year_axis.row_index else ""
            generated.append(GeneratedIncrementCell(new_row, target_column, value, True))
    else:
        target_column = column_remap[existing_target]
    value_by_target_row = {
        row_mapping[item.data_no]: values_by_item.get(item.data_no, "")
        for item in active_items
    }
    for body_offset, old_row in enumerate(body_rows):
        new_row = len(header_rows) + body_offset
        for old_column in kept_columns:
            new_column = column_remap[old_column]
            value = values.get((old_row, old_column), "")
            if new_column == target_column and old_row in value_by_target_row:
                value = value_by_target_row[old_row]
            generated.append(GeneratedIncrementCell(new_row, new_column, value, False))
        if existing_target is None:
            generated.append(GeneratedIncrementCell(
                new_row,
                target_column,
                value_by_target_row.get(old_row, ""),
                False,
            ))
    replacement = IncrementStructureReplacement(
        cells=tuple(generated),
        header_count=len(header_rows),
        row_count=len(body_rows),
        column_count=len(kept_columns) + (1 if existing_target is None else 0),
        mode="year_column_updated" if existing_target is not None else "year_column_appended",
    )
    return IncrementApplication(
        {},
        (
            f"{removed_year}년 열을 제외하고 {target_year}년 열을 추가했습니다."
            if removed_year is not None
            else f"기존 {target_year}년 열을 갱신했습니다."
        ),
        True,
        "YEAR_COLUMN_UPDATED" if existing_target is not None else "YEAR_COLUMN_APPENDED",
        {
            "update_mode": "time_columns",
            "target_year": target_year,
            "removed_year": removed_year,
            "applied_cells": len(value_by_target_row),
        },
        replacement,
    )


def build_time_series_application(
    *,
    cells: list[DatabaseRow],
    dataset: IncrementDataset,
    active_items: list[IncrementItem],
    column_mapping: dict[int, int],
    year_axis: YearRowAxis,
    retention_mode: str,
) -> IncrementApplication:
    """Append one reference year and roll off only the oldest displayed year."""
    target_year = target_reference_year(dataset)
    if target_year is None:
        return IncrementApplication({}, "증분 기준연도가 없습니다.", False, "TARGET_YEAR_MISSING")
    source_rows = sorted({value.row_no for value in dataset.values})
    if len(source_rows) != 1:
        return IncrementApplication({}, "연도표 증분 행이 한 개가 아닙니다.", False, "YEAR_ROW_COUNT_MISMATCH")
    values_by_coordinate = {
        (value.row_no, value.data_no): value.value
        for value in dataset.values
    }
    source_row = source_rows[0]
    existing_target = next(
        (row for row, year in year_axis.years_by_row.items() if year == target_year),
        None,
    )
    if existing_target is not None:
        overlays = {
            (existing_target, column_mapping[item.data_no]): values_by_coordinate.get(
                (source_row, item.data_no), ""
            )
            for item in active_items
        }
        return IncrementApplication(
            overlays,
            f"기존 {target_year}년 행에 증분 키 {dataset.key}의 값 {len(overlays)}개를 갱신했습니다.",
            True,
            "YEAR_ROW_UPDATED",
            {
                "update_mode": "time_series",
                "row_match_method": "exact_reference_year",
                "target_year": target_year,
                "applied_cells": len(overlays),
            },
        )

    latest_year = max(year_axis.years_by_row.values())
    if target_year <= latest_year:
        return IncrementApplication(
            {},
            f"증분 기준연도 {target_year}가 표의 마지막 연도 {latest_year}보다 새롭지 않아 자동 반영하지 않았습니다.",
            False,
            "YEAR_SEQUENCE_CONFLICT",
            {"target_year": target_year, "latest_year": latest_year},
        )

    oldest_year = min(year_axis.years_by_row.values()) if retention_mode == "rolling_window" else None
    oldest_rows = {
        row for row, year in year_axis.years_by_row.items() if year == oldest_year
    } if oldest_year is not None else set()
    header_rows = sorted({int(cell["row_index"]) for cell in cells if bool(cell["is_header"])})
    body_rows = sorted({int(cell["row_index"]) for cell in cells if not bool(cell["is_header"])})
    columns = sorted({int(cell["col_index"]) for cell in cells})
    values = {
        (int(cell["row_index"]), int(cell["col_index"])): str(cell["text_value"] or "")
        for cell in cells
    }
    generated: list[GeneratedIncrementCell] = []
    for new_row, old_row in enumerate(header_rows):
        for column in columns:
            generated.append(GeneratedIncrementCell(
                new_row, column, values.get((old_row, column), ""), True,
            ))
    kept_rows = [row for row in body_rows if row not in oldest_rows]
    for body_offset, old_row in enumerate(kept_rows):
        target_row = len(header_rows) + body_offset
        for column in columns:
            generated.append(GeneratedIncrementCell(
                target_row, column, values.get((old_row, column), ""), False,
            ))
    appended_row = len(header_rows) + len(kept_rows)
    increment_values = {
        column_mapping[item.data_no]: values_by_coordinate.get((source_row, item.data_no), "")
        for item in active_items
    }
    for column in columns:
        value = str(target_year) if column == year_axis.column_index else increment_values.get(column, "")
        generated.append(GeneratedIncrementCell(appended_row, column, value, False))
    replacement = IncrementStructureReplacement(
        cells=tuple(generated),
        header_count=len(header_rows),
        row_count=len(body_rows),
        column_count=len(columns),
        mode="year_appended",
    )
    return IncrementApplication(
        {},
        (
            f"{oldest_year}년 행을 제외하고 {target_year}년 행을 추가해 증분 키 {dataset.key}를 반영했습니다."
            if oldest_year is not None
            else f"기존 연도를 유지하고 {target_year}년 행을 추가해 증분 키 {dataset.key}를 반영했습니다."
        ),
        True,
        "YEAR_APPENDED",
        {
            "update_mode": "time_series",
            "row_match_method": "append_reference_year",
            "target_year": target_year,
            "removed_year": oldest_year,
            "preserved_years": sorted(year for year in year_axis.years_by_row.values() if year != oldest_year),
            "applied_cells": len(increment_values),
        },
        replacement,
    )


def build_grouped_time_row_application(
    *,
    cells: list[DatabaseRow],
    dataset: IncrementDataset,
    active_items: list[IncrementItem],
    year_axis: YearRowAxis,
    retention_mode: str,
) -> IncrementApplication | None:
    target_year = target_reference_year(dataset)
    source_rows = sorted({value.row_no for value in dataset.values})
    if target_year is None or len(source_rows) != 1:
        return None
    groups: dict[str, list[IncrementItem]] = defaultdict(list)
    group_order: list[str] = []
    for item in ordered_active_increment_items(dataset, active_items):
        path = increment_item_path(item)
        if len(path) < 2:
            continue
        group = path[0]
        if group not in groups:
            group_order.append(group)
        groups[group].append(item)
    if len(groups) < 2:
        return None

    header_paths = table_header_paths(cells)
    columns = sorted(header_paths)
    leaf_by_column = {
        column: normalized(path[-1]) if path else ""
        for column, path in header_paths.items()
    }
    item_columns: dict[int, int] = {}
    for group in group_order:
        used: set[int] = set()
        for item in groups[group]:
            leaf = normalized(increment_item_path(item)[-1])
            candidates = [
                (1.0 if leaf == target_leaf else SequenceMatcher(None, leaf, target_leaf).ratio(), column)
                for column, target_leaf in leaf_by_column.items()
                if column != year_axis.column_index and column not in used
            ]
            if not candidates:
                return None
            score, column = max(candidates)
            if score < 0.82:
                return None
            item_columns[item.data_no] = column
            used.add(column)

    header_rows = sorted({int(cell["row_index"]) for cell in cells if bool(cell["is_header"])})
    body_rows = sorted({int(cell["row_index"]) for cell in cells if not bool(cell["is_header"])})
    all_columns = sorted({int(cell["col_index"]) for cell in cells})
    values = {
        (int(cell["row_index"]), int(cell["col_index"])): str(cell["text_value"] or "")
        for cell in cells
    }
    existing_target_rows = [
        row for row, year in year_axis.years_by_row.items() if year == target_year
    ]
    if existing_target_rows:
        removed_rows = set(existing_target_rows)
        removed_year: int | None = None
    else:
        latest_year = max(year_axis.years_by_row.values())
        if target_year <= latest_year:
            return None
        if retention_mode == "rolling_window":
            removed_year = min(year_axis.years_by_row.values())
            removed_rows = {
                row for row, year in year_axis.years_by_row.items() if year == removed_year
            }
        else:
            removed_year = None
            removed_rows = set()
    kept_body_rows = [row for row in body_rows if row not in removed_rows]
    generated: list[GeneratedIncrementCell] = []
    for new_row, old_row in enumerate(header_rows):
        for column in all_columns:
            generated.append(GeneratedIncrementCell(
                new_row, column, values.get((old_row, column), ""), True,
            ))
    for body_offset, old_row in enumerate(kept_body_rows):
        new_row = len(header_rows) + body_offset
        for column in all_columns:
            value = values.get((old_row, column), "")
            if (
                column == year_axis.column_index
                and not value.strip()
                and old_row in year_axis.years_by_row
            ):
                value = str(year_axis.years_by_row[old_row])
            generated.append(GeneratedIncrementCell(
                new_row, column, value, False,
            ))
    source_row = source_rows[0]
    increment_values = {
        value.data_no: value.value
        for value in dataset.values
        if value.row_no == source_row
    }
    for group_offset, group in enumerate(group_order):
        new_row = len(header_rows) + len(kept_body_rows) + group_offset
        by_column = {
            item_columns[item.data_no]: increment_values.get(item.data_no, "")
            for item in groups[group]
        }
        for column in all_columns:
            value = str(target_year) if column == year_axis.column_index else by_column.get(column, "")
            if not value and "비율" in normalized(group) and leaf_by_column.get(column) in {"계", "전체", "합계"}:
                value = "100"
            generated.append(GeneratedIncrementCell(new_row, column, value, False))
    replacement = IncrementStructureReplacement(
        cells=tuple(generated),
        header_count=len(header_rows),
        row_count=len(kept_body_rows) + len(group_order),
        column_count=len(all_columns),
        mode="grouped_year_rows",
    )
    return IncrementApplication(
        {},
        f"{target_year}년의 {len(group_order)}개 세부 행을 추가했습니다.",
        True,
        "GROUPED_YEAR_ROWS_APPENDED",
        {
            "update_mode": "grouped_time_rows",
            "target_year": target_year,
            "removed_year": removed_year,
            "row_groups": group_order,
            "applied_cells": len(increment_values),
        },
        replacement,
    )


def build_structure_replacement_application(
    *,
    cells: list[DatabaseRow],
    dataset: IncrementDataset,
    active_items: list[IncrementItem],
    trigger: str,
    retention_mode: str = "replace",
) -> IncrementApplication | None:
    """Build a complete, deterministic table when a verified key changed shape.

    The increment is allowed to define a new structure only when every value
    has item metadata and every active item has a unique hierarchical path.
    Multi-row categorical snapshots replace the body.  A single measure row
    without a row dimension keeps historical rows and changes only the target
    row, so a new column never erases prior years.
    """

    ordered_items = ordered_active_increment_items(dataset, active_items)
    if len(ordered_items) != len(active_items):
        return None
    item_paths = {
        item.data_no: increment_item_path(item)
        for item in ordered_items
    }
    if any(not path for path in item_paths.values()):
        return None
    normalized_paths = [normalized(">".join(item_paths[item.data_no])) for item in ordered_items]
    if len(set(normalized_paths)) != len(normalized_paths):
        return None

    source_rows = sorted({value.row_no for value in dataset.values})
    if not source_rows:
        return None
    values_by_coordinate = {
        (value.row_no, value.data_no): value.value
        for value in dataset.values
    }
    old_header_rows = sorted({int(cell["row_index"]) for cell in cells if bool(cell["is_header"])})
    old_body_rows = sorted({int(cell["row_index"]) for cell in cells if not bool(cell["is_header"])})
    old_columns = sorted({int(cell["col_index"]) for cell in cells})
    old_values = {
        (int(cell["row_index"]), int(cell["col_index"])): str(cell["text_value"] or "")
        for cell in cells
    }
    old_paths = table_header_paths(cells)
    old_raw_paths = table_raw_header_paths(cells)
    partial_mapping, _ = match_increment_items_to_columns(ordered_items, old_paths)
    year_axis = detect_year_row_axis(cells, old_body_rows)

    first_item = ordered_items[0]
    first_values = [
        normalized(values_by_coordinate.get((row_no, first_item.data_no), ""))
        for row_no in source_rows
    ]
    non_empty_first_values = [value for value in first_values if value]
    has_row_dimension = bool(non_empty_first_values) and sum(
        is_dimension_label(value) for value in non_empty_first_values
    ) >= max(1, (len(non_empty_first_values) + 1) // 2)
    preserve_history = (
        len(source_rows) == 1
        and not has_row_dimension
        and len(old_body_rows) > 1
        and year_axis is not None
    )

    generated_columns: list[tuple[tuple[str, ...], int | None, IncrementItem | None]] = []
    mode_evidence: dict[str, Any] = {}
    if preserve_history:
        matched_old_columns = sorted(partial_mapping.values())
        first_measure_column = matched_old_columns[0] if matched_old_columns else 1
        descriptor_columns = [column for column in old_columns if column < first_measure_column]
        if not descriptor_columns and old_columns:
            descriptor_columns = [old_columns[0]]
        for column in descriptor_columns:
            path = old_raw_paths.get(column) or old_paths.get(column) or (f"열 {column + 1}",)
            generated_columns.append((path, column, None))
    for item in ordered_items:
        translated_path = translated_increment_path(
            item_paths[item.data_no],
            cells,
            partial_mapping.get(item.data_no),
        )
        generated_columns.append((translated_path, partial_mapping.get(item.data_no), item))

    header_depth = max(len(path) for path, _, _ in generated_columns)
    generated: list[GeneratedIncrementCell] = []
    for column_index, (path, _, _) in enumerate(generated_columns):
        for row_index in range(header_depth):
            generated.append(
                GeneratedIncrementCell(
                    row_index=row_index,
                    col_index=column_index,
                    value=path[min(row_index, len(path) - 1)],
                    is_header=True,
                )
            )

    if preserve_history:
        target_year = target_reference_year(dataset)
        assert year_axis is not None
        if target_year is None:
            return None
        existing_target = next(
            (row for row, year in year_axis.years_by_row.items() if year == target_year),
            None,
        )
        if existing_target is None:
            latest_year = max(year_axis.years_by_row.values())
            if target_year <= latest_year:
                return None
            if retention_mode == "rolling_window":
                oldest_year = min(year_axis.years_by_row.values())
                oldest_rows = {
                    row for row, year in year_axis.years_by_row.items() if year == oldest_year
                }
                destination_rows = [row for row in old_body_rows if row not in oldest_rows]
            else:
                oldest_year = None
                destination_rows = list(old_body_rows)
        else:
            oldest_year = None
            destination_rows = list(old_body_rows)
        for body_offset, old_row in enumerate(destination_rows):
            target_row = header_depth + body_offset
            for column_index, (_, old_column, item) in enumerate(generated_columns):
                value = old_values.get((old_row, old_column), "") if old_column is not None else ""
                generated.append(GeneratedIncrementCell(target_row, column_index, value, False))
        source_row = source_rows[0]
        if existing_target is None:
            target_row = header_depth + len(destination_rows)
            body_row_count = len(destination_rows) + 1
        else:
            target_row = header_depth + destination_rows.index(existing_target)
            body_row_count = len(destination_rows)
        for column_index, (_, old_column, item) in enumerate(generated_columns):
            if item is not None:
                value = values_by_coordinate.get((source_row, item.data_no), "")
            elif old_column == year_axis.column_index:
                value = str(target_year)
            elif existing_target is None:
                value = ""
            else:
                continue
            generated.append(GeneratedIncrementCell(target_row, column_index, value, False))
        mode = "year_updated" if existing_target is not None else "year_appended"
        mode_evidence = {
            "update_mode": "time_series",
            "target_year": target_year,
            "removed_year": oldest_year,
            "applied_cells": len(active_items),
        }
    else:
        for body_offset, source_row in enumerate(source_rows):
            target_row = header_depth + body_offset
            for column_index, (_, _, item) in enumerate(generated_columns):
                value = (
                    values_by_coordinate.get((source_row, item.data_no), "")
                    if item is not None
                    else ""
                )
                generated.append(GeneratedIncrementCell(target_row, column_index, value, False))
        mode = "snapshot_rebuilt"
        body_row_count = len(source_rows)
        mode_evidence = {"update_mode": "snapshot", "applied_cells": len(dataset.values)}

    # Later writes for the target history row intentionally replace earlier
    # preserved values. Collapse coordinates before persisting.
    generated_by_coordinate = {
        (cell.row_index, cell.col_index): cell for cell in generated
    }
    replacement = IncrementStructureReplacement(
        cells=tuple(
            generated_by_coordinate[key]
            for key in sorted(generated_by_coordinate)
        ),
        header_count=header_depth,
        row_count=body_row_count,
        column_count=len(generated_columns),
        mode=mode,
    )
    old_shape = {"rows": len(old_body_rows), "columns": len(old_columns), "header_rows": len(old_header_rows)}
    new_shape = {"rows": body_row_count, "columns": len(generated_columns), "header_rows": header_depth}
    return IncrementApplication(
        {},
        (
            f"증분 키 {dataset.key}의 항목 정보로 표 구조를 안전하게 재구성했습니다. "
            f"본문 {old_shape['rows']}행×{old_shape['columns']}열에서 "
            f"{new_shape['rows']}행×{new_shape['columns']}열로 갱신했습니다."
        ),
        True,
        "STRUCTURE_REBUILT",
        {
            "rebuild_trigger": trigger,
            "rebuild_mode": mode,
            "old_shape": old_shape,
            "new_shape": new_shape,
            "header_paths": [list(item_paths[item.data_no]) for item in ordered_items],
            **mode_evidence,
        },
        replacement,
    )


def increment_item_path(item: IncrementItem) -> tuple[str, ...]:
    raw = item.full_name or item.label
    parts = tuple(part.strip() for part in raw.split(">") if part.strip())
    return parts or ((item.label or str(item.data_no)).strip(),)


def table_has_year_dimension(
    body_rows: list[int],
    columns: list[int],
    values: dict[tuple[int, int], str],
) -> bool:
    if not body_rows or not columns:
        return False
    first_column = columns[0]
    labels = [
        normalized(values.get((row_index, first_column), ""))
        for row_index in body_rows
    ]
    non_empty = [label for label in labels if label]
    if not non_empty:
        return False
    year_like = sum(bool(re.fullmatch(r"(?:19|20)\d{2}(?:\d{2})?", label)) for label in non_empty)
    return year_like >= max(1, (len(non_empty) + 1) // 2)


def ordered_active_increment_items(
    dataset: IncrementDataset,
    active_items: list[IncrementItem],
) -> list[IncrementItem]:
    all_path_orders: dict[tuple[str, ...], tuple[int, int]] = {}
    for item in dataset.items:
        path = tuple(normalized(part) for part in increment_item_path(item))
        all_path_orders[path] = min(
            all_path_orders.get(path, (item.order, item.data_no)),
            (item.order, item.data_no),
        )

    def ordering(item: IncrementItem) -> tuple[Any, ...]:
        path = tuple(normalized(part) for part in increment_item_path(item))
        prefix_orders = []
        for depth in range(1, len(path) + 1):
            prefix_orders.append(all_path_orders.get(path[:depth], (item.order, item.data_no)))
        return (*prefix_orders, (item.data_no, item.data_no))

    return sorted(active_items, key=ordering)


def table_raw_header_paths(cells: list[DatabaseRow]) -> dict[int, tuple[str, ...]]:
    header_rows = sorted({int(row["row_index"]) for row in cells if bool(row["is_header"])})
    columns = sorted({int(row["col_index"]) for row in cells})
    raw = {
        (int(row["row_index"]), int(row["col_index"])): str(row["text_value"] or "").strip()
        for row in cells
        if bool(row["is_header"])
    }
    result: dict[int, tuple[str, ...]] = {}
    inherited_by_row: dict[int, str] = {}
    for column in columns:
        parts: list[str] = []
        for row_index in header_rows:
            value = raw.get((row_index, column), "")
            if value:
                inherited_by_row[row_index] = value
            value = value or inherited_by_row.get(row_index, "")
            if value and (not parts or normalized(display_header_text(parts[-1])) != normalized(display_header_text(value))):
                parts.append(value)
        result[column] = tuple(parts)
    return result


def translated_increment_path(
    path: tuple[str, ...],
    cells: list[DatabaseRow],
    matched_column: int | None,
) -> tuple[str, ...]:
    if matched_column is not None:
        old_path = table_raw_header_paths(cells).get(matched_column, ())
        if len(old_path) == len(path):
            return tuple(
                old_value
                if normalized(path_part) in normalized(display_header_text(old_value))
                else path_part
                for path_part, old_value in zip(path, old_path)
            )
    translations: dict[str, str] = {}
    for cell in cells:
        if not bool(cell["is_header"]):
            continue
        raw = str(cell["text_value"] or "").strip()
        display = display_header_text(raw)
        if raw and display:
            translations.setdefault(normalized(display), raw)
    return tuple(translations.get(normalized(part), part) for part in path)


def quarantine_unsafe_positional_results(
    connection: DatabaseConnection,
    *,
    report_id: int,
    datasets: dict[str, IncrementDataset],
) -> int:
    """Undo legacy position-only overlays that have no semantic column map.

    A matching row/column count cannot prove that source data numbers have the
    same meaning as the displayed columns.  Older drafts accepted that weak
    condition and could therefore put every value in the wrong column while
    still reporting success.  Restore untouched draft tables from their
    selected predecessor and move them back to the connection review queue.
    """

    rows = connection.execute(
        """
        SELECT status.table_id, status.source_table_id, table_row.code,
               table_row.manually_edited_at, mapping.source_key
        FROM generated_report_table_status status
        JOIN stat_tables table_row ON table_row.id = status.table_id
        LEFT JOIN report_incremental_table_mappings mapping
          ON mapping.report_id = status.report_id
         AND mapping.table_code = table_row.code
        WHERE status.report_id = ?
          AND status.generation_status = 'increment_applied'
          AND status.generation_message LIKE '%항목 정보 없이 값 구조가 일치하여%'
        """,
        (report_id,),
    ).fetchall()
    quarantined = 0
    with connection:
        for row in rows:
            source_key = str(row["source_key"] or "")
            table_id = int(row["table_id"])
            source_table_id = row["source_table_id"]
            if source_table_id is not None and not str(row["manually_edited_at"] or "").strip():
                connection.execute(
                    "DELETE FROM stat_table_cells WHERE table_id = ?",
                    (table_id,),
                )
                connection.execute(
                    """
                    INSERT INTO stat_table_cells (
                        table_id, row_index, col_index, text_value, numeric_value,
                        is_header, footnote_marker, source_coordinate, text_color,
                        parse_warnings_json
                    )
                    SELECT ?, row_index, col_index, text_value, numeric_value,
                           is_header, footnote_marker, source_coordinate, text_color,
                           parse_warnings_json
                    FROM stat_table_cells
                    WHERE table_id = ?
                    """,
                    (table_id, int(source_table_id)),
                )
            message = (
                f"연결 키 {source_key or '-'}는 확인했지만 표항목 정보가 없어 자료번호와 "
                "기존 열의 의미를 검증할 수 없습니다. 기존 값을 복원하고 증분 연결 확인으로 전환했습니다."
            )
            connection.execute(
                """
                UPDATE generated_report_table_status
                SET generation_status = 'mapping_review', generation_message = ?
                WHERE report_id = ? AND table_id = ?
                """,
                (message, report_id, table_id),
            )
            connection.execute(
                """
                UPDATE report_incremental_table_mappings
                SET mapping_status = 'review', updated_at = CURRENT_TIMESTAMP
                WHERE report_id = ? AND table_code = ?
                """,
                (report_id, str(row["code"])),
            )
            quarantined += 1
    return quarantined


def apply_increment_by_position(
    *,
    cells: list[DatabaseRow],
    body_rows: list[int],
    target_rows: list[int],
    dataset: IncrementDataset,
) -> tuple[dict[tuple[int, int], str], str, bool]:
    """Use the uploaded value layout only when it exactly fits the old table.

    Several increment exports omit ``표항목`` for an otherwise unchanged
    statistic.  Its values still retain a stable row/column order.  We use
    that order only for an exact-title connection and only if every value row
    has either the same number of columns as the old table, or exactly one
    fewer (the old table's leading label/year column).  Anything less exact is
    deliberately left for manual confirmation.
    """
    values_by_row: dict[int, list[IncrementValue]] = defaultdict(list)
    for value in dataset.values:
        values_by_row[value.row_no].append(value)
    if not values_by_row or not body_rows:
        return {}, f"연결 키 {dataset.key}에 항목 정보와 반영 가능한 값이 없어 확인이 필요합니다.", False

    columns = sorted({int(row["col_index"]) for row in cells})
    source_rows = [values_by_row[row_no] for row_no in sorted(values_by_row)]
    value_counts = {len(values) for values in source_rows}
    if len(value_counts) != 1:
        return {}, f"연결 키 {dataset.key}의 행별 값 개수가 달라 자동 반영하지 않았습니다.", False
    value_count = next(iter(value_counts))
    if value_count == len(columns):
        target_columns = columns
    elif value_count == len(columns) - 1:
        target_columns = columns[1:]
    else:
        return {}, f"연결 키 {dataset.key}의 값 열 수가 기존 표 구조와 달라 자동 반영하지 않았습니다.", False

    if len(source_rows) == len(body_rows):
        destination_rows = body_rows
    elif len(source_rows) == 1 and target_rows:
        destination_rows = [target_rows[-1]]
    else:
        return {}, f"연결 키 {dataset.key}의 값 행 수가 기존 표 구조와 달라 자동 반영하지 않았습니다.", False

    overlays: dict[tuple[int, int], str] = {}
    for row_index, source_values in zip(destination_rows, source_rows):
        ordered_values = sorted(source_values, key=lambda value: value.data_no)
        for column_index, value in zip(target_columns, ordered_values):
            overlays[(row_index, column_index)] = value.value
    return (
        overlays,
        f"증분 키 {dataset.key}는 항목 정보 없이 값 구조가 일치하여 {len(overlays)}개 셀을 순서대로 반영했습니다.",
        True,
    )


def infer_increment_recipe_from_tables(
    connection: DatabaseConnection,
    *,
    source_table_id: int,
    reference_table_id: int,
    dataset: IncrementDataset,
) -> dict[str, Any] | None:
    def axes(table_id: int) -> tuple[YearRowAxis | None, YearColumnAxis | None]:
        cells = connection.execute(
            "SELECT row_index, col_index, text_value, is_header FROM stat_table_cells WHERE table_id = ? ORDER BY row_index, col_index",
            (table_id,),
        ).fetchall()
        body_rows = sorted({int(cell["row_index"]) for cell in cells if not bool(cell["is_header"])})
        return detect_year_row_axis(cells, body_rows), detect_year_column_axis(cells)

    source_row_axis, source_column_axis = axes(source_table_id)
    target_row_axis, target_column_axis = axes(reference_table_id)
    target_year = target_reference_year(dataset)
    if source_row_axis is not None and target_row_axis is not None:
        source_years = set(source_row_axis.years_by_row.values())
        target_years = set(target_row_axis.years_by_row.values())
        if target_year is not None and target_year not in target_years:
            return None
        grouped = max(Counter(source_row_axis.years_by_row.values()).values(), default=1) > 1
        retention = "append_history" if source_years < target_years else "rolling_window"
        return {
            "update_mode": "grouped_time_rows" if grouped else "time_rows",
            "retention_mode": retention,
            "window_size": len(target_years),
            "evidence": {"source_years": sorted(source_years), "target_years": sorted(target_years)},
        }
    if source_column_axis is not None and target_column_axis is not None:
        source_years = set(source_column_axis.years_by_column.values())
        target_years = set(target_column_axis.years_by_column.values())
        if target_year is not None and target_year not in target_years:
            return None
        retention = "append_history" if source_years < target_years else "rolling_window"
        return {
            "update_mode": "time_columns",
            "retention_mode": retention,
            "window_size": len(target_years),
            "evidence": {"source_years": sorted(source_years), "target_years": sorted(target_years)},
        }
    return {
        "update_mode": "snapshot",
        "retention_mode": "replace",
        "window_size": 1,
        "evidence": {"target_year": target_year},
    }


def synchronize_report_layout_by_title(
    connection: DatabaseConnection,
    *,
    report_id: int,
    reference_report_id: int,
) -> int:
    source_by_title: dict[str, list[DatabaseRow]] = defaultdict(list)
    target_by_title: dict[str, list[DatabaseRow]] = defaultdict(list)
    for row in connection.execute(
        "SELECT id, code, title, table_order FROM stat_tables WHERE report_id = ?",
        (report_id,),
    ).fetchall():
        source_by_title[normalized(str(row["title"] or ""))].append(row)
    for row in connection.execute(
        "SELECT id, code, title, table_order FROM stat_tables WHERE report_id = ?",
        (reference_report_id,),
    ).fetchall():
        target_by_title[normalized(str(row["title"] or ""))].append(row)
    candidates: list[tuple[str, str, int, int]] = []
    for title, source_rows in source_by_title.items():
        target_rows = target_by_title.get(title, [])
        if not source_rows or len(source_rows) != len(target_rows):
            continue
        ordered_sources = sorted(source_rows, key=lambda row: (int(row["table_order"] or 0), str(row["code"] or "")))
        ordered_targets = sorted(target_rows, key=lambda row: (int(row["table_order"] or 0), str(row["code"] or "")))
        for source, target in zip(ordered_sources, ordered_targets):
            candidates.append((
                str(source["code"] or ""),
                str(target["code"] or ""),
                int(source["id"]),
                int(target["table_order"] or 0),
            ))
    current_codes = {
        str(row["code"])
        for row in connection.execute(
            "SELECT code FROM stat_tables WHERE report_id = ?",
            (report_id,),
        ).fetchall()
    }
    plans = list(candidates)
    while True:
        planned_sources = {source for source, _, _, _ in plans}
        filtered = [
            plan for plan in plans
            if plan[0] == plan[1] or plan[1] not in current_codes - planned_sources
        ]
        if len(filtered) == len(plans):
            break
        plans = filtered
    temporary: list[tuple[str, str, str, int, int]] = []
    for index, (current, target, table_id, order) in enumerate(plans):
        temp = f"__reference_layout_{report_id}_{index}__"
        connection.execute("UPDATE stat_tables SET code = ? WHERE id = ?", (temp, table_id))
        connection.execute(
            "UPDATE report_incremental_table_mappings SET table_code = ? WHERE report_id = ? AND table_code = ?",
            (temp, report_id, current),
        )
        temporary.append((temp, current, target, table_id, order))
    changed = 0
    for temp, current, target, table_id, order in temporary:
        connection.execute(
            "UPDATE stat_tables SET code = ?, table_order = ? WHERE id = ?",
            (target, order, table_id),
        )
        connection.execute(
            "UPDATE report_incremental_table_mappings SET table_code = ? WHERE report_id = ? AND table_code = ?",
            (target, report_id, temp),
        )
        changed += int(current != target)
    return changed


def apply_target_publication_codes(
    connection: DatabaseConnection,
    report_id: int,
    datasets: dict[str, IncrementDataset],
) -> int:
    """Apply explicit publication numbers carried by an increment export.

    Identity remains the M key.  Publication numbers are presentation data
    and may change every year, so all renames use temporary codes first.
    """
    rows = connection.execute(
        """
        SELECT mapping.table_code, mapping.source_key, table_row.id AS table_id
        FROM report_incremental_table_mappings mapping
        JOIN stat_tables table_row
          ON table_row.report_id = mapping.report_id
         AND table_row.code = mapping.table_code
        WHERE mapping.report_id = ? AND mapping.mapping_status = 'mapped'
        """,
        (report_id,),
    ).fetchall()
    plans: list[tuple[str, str, int, int]] = []
    for row in rows:
        dataset = datasets.get(str(row["source_key"] or ""))
        if dataset is None or not dataset.target_code.strip():
            continue
        current = str(row["table_code"] or "")
        target = dataset.target_code.strip()
        if current != target or dataset.publication_order:
            plans.append((current, target, int(row["table_id"]), dataset.publication_order))
    if not plans:
        return 0
    targets = [target for _, target, _, _ in plans]
    if len(set(targets)) != len(targets):
        raise ValueError("증분의 새 표 번호가 중복되어 연보 번호를 자동 변경할 수 없습니다.")
    current_codes = {
        str(row["code"])
        for row in connection.execute(
            "SELECT code FROM stat_tables WHERE report_id = ?",
            (report_id,),
        ).fetchall()
    }
    while True:
        renamed_codes = {current for current, _, _, _ in plans}
        filtered = [
            plan for plan in plans
            if plan[1] not in current_codes - renamed_codes
        ]
        if len(filtered) == len(plans):
            break
        plans = filtered
    if not plans:
        return 0
    temporary: list[tuple[str, str, int, int]] = []
    for index, (current, target, table_id, order) in enumerate(plans):
        temp = f"__increment_code_{report_id}_{index}__"
        connection.execute("UPDATE stat_tables SET code = ? WHERE id = ?", (temp, table_id))
        connection.execute(
            "UPDATE report_incremental_table_mappings SET table_code = ? WHERE report_id = ? AND table_code = ?",
            (temp, report_id, current),
        )
        temporary.append((temp, target, table_id, order))
    for temp, target, table_id, order in temporary:
        connection.execute(
            "UPDATE stat_tables SET code = ?, table_order = CASE WHEN ? > 0 THEN ? ELSE table_order END WHERE id = ?",
            (target, order, order, table_id),
        )
        connection.execute(
            "UPDATE report_incremental_table_mappings SET table_code = ? WHERE report_id = ? AND table_code = ?",
            (target, report_id, temp),
        )
    return len(plans)


def record_unmatched_increment_mappings(
    connection: DatabaseConnection, *, report_id: int, datasets: dict[str, IncrementDataset],
    matched_keys: set[str],
) -> int:
    count = 0
    for dataset in datasets.values():
        if dataset.key in matched_keys or is_deleted_source_status(dataset.status):
            continue
        connection.execute(
            """
            INSERT INTO report_incremental_table_mappings (
                report_id, table_code, source_key, match_method, confidence,
                mapping_status, reason_code, evidence_json, candidates_json
            ) VALUES (?, ?, ?, 'new_increment', 1, 'review', 'UNMATCHED_NEW_INCREMENT', ?, '[]')
            ON CONFLICT(report_id, table_code) DO UPDATE SET
                source_key = excluded.source_key,
                match_method = excluded.match_method,
                confidence = excluded.confidence,
                mapping_status = excluded.mapping_status,
                reason_code = excluded.reason_code,
                evidence_json = excluded.evidence_json,
                candidates_json = excluded.candidates_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                report_id,
                f"미연결-{dataset.key}",
                dataset.key,
                json.dumps(
                    {
                        "title": dataset.title,
                        "management_number": dataset.management_number,
                        "department": dataset.department,
                        "items": len(dataset.items),
                        "values": len(dataset.values),
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        count += 1
    return count


def increment_matrix(dataset: IncrementDataset) -> list[list[str]]:
    items = dataset.items or [IncrementItem(0, "표시값", "표시값", 0)]
    headers = [item.full_name or item.label or str(item.data_no) for item in items]
    by_row: dict[int, dict[int, str]] = defaultdict(dict)
    for value in dataset.values:
        by_row[value.row_no][value.data_no] = value.value
    return [headers] + [[row.get(item.data_no, "") for item in items] for _, row in sorted(by_row.items())]


def current_cell_values(
    connection: DatabaseConnection,
    table_id: int,
) -> dict[tuple[int, int], str]:
    return {
        (int(row["row_index"]), int(row["col_index"])): str(row["text_value"] or "")
        for row in connection.execute(
            "SELECT row_index, col_index, text_value FROM stat_table_cells WHERE table_id = ?",
            (table_id,),
        ).fetchall()
    }


def application_change_count(application: IncrementApplication) -> int:
    if "applied_cells" in application.evidence:
        return int(application.evidence["applied_cells"] or 0)
    if application.replacement is not None:
        return sum(not cell.is_header for cell in application.replacement.cells)
    return len(application.overlays)


def replace_cells_from_increment(
    connection: DatabaseConnection,
    *,
    table_id: int,
    replacement: IncrementStructureReplacement,
) -> None:
    connection.execute("DELETE FROM stat_table_cells WHERE table_id = ?", (table_id,))
    connection.executemany(
        """
        INSERT INTO stat_table_cells (
            table_id, row_index, col_index, text_value, numeric_value,
            is_header, footnote_marker, source_coordinate, text_color,
            parse_warnings_json
        ) VALUES (?, ?, ?, ?, ?, ?, '', '', '', '[]')
        """,
        [
            (
                table_id,
                cell.row_index,
                cell.col_index,
                cell.value,
                None if cell.is_header else parse_numeric_value(cell.value),
                int(cell.is_header),
            )
            for cell in replacement.cells
        ],
    )
    total_rows = replacement.header_count + replacement.row_count
    connection.execute(
        "UPDATE stat_tables SET cell_range = ? WHERE id = ?",
        (
            f"R1C1:R{max(1, total_rows)}C{max(1, replacement.column_count)}",
            table_id,
        ),
    )


def normalized_reference_time(value: str) -> str:
    cleaned = (value or "").strip()
    year_match = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", cleaned)
    if not year_match:
        return cleaned
    if re.search(r"(?:19|20)\d{2}\D+\d{1,2}\D+\d{1,2}", cleaned):
        return cleaned
    return f"{year_match.group(1)}. 12. 31."


def update_table_reference_metadata(
    connection: DatabaseConnection,
    table_id: int,
    dataset: IncrementDataset,
) -> None:
    reference_time = normalized_reference_time(dataset.reference_time)
    if not reference_time:
        return
    connection.execute(
        "UPDATE stat_tables SET base_date = ? WHERE id = ?",
        (reference_time, table_id),
    )


def mark_table_validation_stale_after_increment(
    connection: DatabaseConnection,
    *,
    report_id: int,
    table_id: int,
) -> None:
    latest_run = connection.execute(
        "SELECT id FROM validation_runs WHERE report_id = ? ORDER BY completed_at DESC, id DESC LIMIT 1",
        (report_id,),
    ).fetchone()
    if latest_run is None:
        return
    connection.execute(
        "UPDATE stat_tables SET edited_after_run_id = ? WHERE id = ?",
        (int(latest_run["id"]), table_id),
    )


def record_cell_overlays(
    connection: DatabaseConnection,
    *,
    report_id: int,
    source_table_id: int,
    target_table_id: int,
    source_key: str,
    overlays: dict[tuple[int, int], str],
) -> None:
    source_values = current_cell_values(connection, source_table_id)
    record_cell_overlays_from_values(
        connection,
        report_id=report_id,
        table_id=target_table_id,
        source_key=source_key,
        base_values=source_values,
        overlays=overlays,
    )


def record_cell_overlays_from_values(
    connection: DatabaseConnection,
    *,
    report_id: int,
    table_id: int,
    source_key: str,
    base_values: dict[tuple[int, int], str],
    overlays: dict[tuple[int, int], str],
) -> None:
    if not overlays:
        return
    connection.executemany(
        """
        INSERT INTO report_incremental_cell_overlays (
            report_id, table_id, row_index, col_index, source_key, base_text, applied_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(report_id, table_id, row_index, col_index) DO UPDATE SET
            source_key = excluded.source_key,
            base_text = excluded.base_text,
            applied_text = excluded.applied_text
        """,
        [
            (
                report_id,
                table_id,
                row_index,
                col_index,
                source_key,
                base_values.get((row_index, col_index), ""),
                value,
            )
            for (row_index, col_index), value in overlays.items()
        ],
    )


def restore_increment_overlays(
    connection: DatabaseConnection,
    *,
    report_id: int,
    table_id: int,
    source_table_id: int | None,
    allow_full_restore: bool,
) -> None:
    overlays = connection.execute(
        """
        SELECT row_index, col_index, base_text, applied_text
        FROM report_incremental_cell_overlays
        WHERE report_id = ? AND table_id = ?
        """,
        (report_id, table_id),
    ).fetchall()
    if overlays:
        for overlay in overlays:
            current = connection.execute(
                """
                SELECT text_value FROM stat_table_cells
                WHERE table_id = ? AND row_index = ? AND col_index = ?
                """,
                (table_id, int(overlay["row_index"]), int(overlay["col_index"])),
            ).fetchone()
            # Preserve a value the user edited after the increment was applied.
            if current is None or str(current["text_value"] or "") != str(overlay["applied_text"] or ""):
                continue
            base_text = str(overlay["base_text"] or "")
            connection.execute(
                """
                UPDATE stat_table_cells SET text_value = ?, numeric_value = ?
                WHERE table_id = ? AND row_index = ? AND col_index = ?
                """,
                (
                    base_text,
                    parse_numeric_value(base_text),
                    table_id,
                    int(overlay["row_index"]),
                    int(overlay["col_index"]),
                ),
            )
        connection.execute(
            "DELETE FROM report_incremental_cell_overlays WHERE report_id = ? AND table_id = ?",
            (report_id, table_id),
        )
        return
    if source_table_id is None or not allow_full_restore:
        return
    # Legacy drafts predate cell provenance.  A never-edited table can still
    # be restored safely from its predecessor before the new key is applied.
    connection.execute("DELETE FROM stat_table_cells WHERE table_id = ?", (table_id,))
    connection.execute(
        """
        INSERT INTO stat_table_cells (
            table_id, row_index, col_index, text_value, numeric_value, is_header,
            footnote_marker, source_coordinate, text_color, parse_warnings_json
        )
        SELECT ?, row_index, col_index, text_value, numeric_value, is_header,
               footnote_marker, source_coordinate, text_color, parse_warnings_json
        FROM stat_table_cells WHERE table_id = ?
        """,
        (table_id, source_table_id),
    )
    connection.execute(
        """
        UPDATE stat_tables
        SET base_date = (SELECT base_date FROM stat_tables WHERE id = ?),
            cell_range = (SELECT cell_range FROM stat_tables WHERE id = ?)
        WHERE id = ?
        """,
        (source_table_id, source_table_id, table_id),
    )


def copy_table(connection: DatabaseConnection, source: DatabaseRow, *, report_id: int, imported_at: str) -> int:
    fields = ("code", "title", "title_en", "section_title", "section_title_en", "domain", "unit", "base_date", "section_file", "table_order", "cell_range", "note", "source", "raw_context", "parse_warnings_json")
    cursor = connection.execute(
        f"INSERT INTO stat_tables (report_id, {', '.join(fields)}, extracted_at) VALUES (?, {', '.join('?' for _ in fields)}, ?)",
        (report_id, *(source[field] for field in fields), imported_at),
    )
    return int(cursor.lastrowid)


def copy_cells(connection: DatabaseConnection, source_id: int, target_id: int, overlays: dict[tuple[int, int], str]) -> None:
    cells = connection.execute("SELECT * FROM stat_table_cells WHERE table_id = ?", (source_id,)).fetchall()
    connection.executemany(
        """INSERT INTO stat_table_cells (table_id, row_index, col_index, text_value, numeric_value, is_header, footnote_marker, source_coordinate, text_color, parse_warnings_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(target_id, int(row["row_index"]), int(row["col_index"]),
          overlays.get((int(row["row_index"]), int(row["col_index"])), str(row["text_value"] or "")),
          parse_numeric_value(overlays.get((int(row["row_index"]), int(row["col_index"])), str(row["text_value"] or ""))),
          int(row["is_header"]), str(row["footnote_marker"] or ""), str(row["source_coordinate"] or ""), str(row["text_color"] or ""), str(row["parse_warnings_json"] or "[]")) for row in cells],
    )


def record_update_batch(connection: DatabaseConnection, *, base_report_id: int, report_id: int,
                        copied: list[tuple[DatabaseRow, int, str, int]], deleted_count: int, new_count: int) -> None:
    changed = sum(status == "increment_applied" for _, _, status, _ in copied)
    unchanged = sum(status == "increment_no_change" for _, _, status, _ in copied)
    changed_cells = sum(cell_count for _, _, status, cell_count in copied if status == "increment_applied")
    cursor = connection.execute(
        """INSERT INTO report_update_batches (base_report_id, report_id, update_kind, changed_table_count, unchanged_table_count, added_table_count, deleted_table_count, changed_cell_count)
           VALUES (?, ?, 'incremental_upload', ?, ?, ?, ?, ?)""",
        (base_report_id, report_id, changed, unchanged, new_count, deleted_count, changed_cells),
    )
    batch_id = int(cursor.lastrowid)
    for base, report_table_id, status, cell_count in copied:
        connection.execute(
            """INSERT INTO report_update_table_diffs (batch_id, table_code, base_table_id, report_table_id, change_type, changed_cell_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (batch_id, str(base["code"]), int(base["id"]), report_table_id,
             "changed" if status == "increment_applied" else "matching", cell_count),
        )


def serialize_datasets(datasets: dict[str, IncrementDataset]) -> dict[str, object]:
    return {key: asdict(dataset) for key, dataset in datasets.items()}


def deserialize_datasets(payload: dict[str, Any]) -> dict[str, IncrementDataset]:
    return {key: IncrementDataset(
        key=str(value.get("key") or key), title=str(value.get("title") or key), status=str(value.get("status") or ""),
        management_number=str(value.get("management_number") or ""), department=str(value.get("department") or ""), reference_time=str(value.get("reference_time") or ""),
        target_code=str(value.get("target_code") or ""), publication_order=int(value.get("publication_order") or 0),
        items=[IncrementItem(**item) for item in value.get("items", [])],
        values=[IncrementValue(**item) for item in value.get("values", [])],
    ) for key, value in payload.items()}


def require_headers(headers: list[str], required: set[str], path: Path) -> None:
    missing = required - set(headers)
    if missing:
        raise ValueError(f"{path.name}에 필수 열이 없습니다: {', '.join(sorted(missing))}")


def cell(row: dict[str, Any], name: str) -> str:
    value = row.get(name)
    if value is None:
        return ""
    return str(value).strip()


def first_cell(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = cell(row, name)
        if value:
            return value
    return ""


def integer(value: str, *, default: int) -> int:
    try:
        return int(float(value)) if value else default
    except ValueError:
        return default


def normalized(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", value.lower())


def normalized_reference_cell(value: str) -> str:
    """Normalize presentation-only differences for completed-edition audits.

    Published cells commonly contain a Korean display value followed by an
    English translation on the next line, while increment-native cells contain
    only the Korean display value.  The audit therefore compares the first
    display line and ignores thousands separators/spacing, but it deliberately
    keeps punctuation that changes a value (decimal points, signs and percent).
    """
    lines = [re.sub(r"\s+", " ", line).strip() for line in str(value or "").splitlines()]
    display = next((line for line in lines if line), "")
    if display in {"", "-", "–", "—"}:
        return ""
    numeric = display.replace(",", "").replace(" ", "").removesuffix("%")
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)%?", numeric):
        return numeric
    return re.sub(r"\s+", "", display).lower()


def reference_cell_matrix(
    connection: DatabaseConnection,
    table_id: int,
) -> dict[tuple[int, int], str]:
    return {
        (int(row["row_index"]), int(row["col_index"])): normalized_reference_cell(
            str(row["text_value"] or "")
        )
        for row in connection.execute(
            """
            SELECT row_index, col_index, text_value
            FROM stat_table_cells
            WHERE table_id = ?
            ORDER BY row_index, col_index
            """,
            (table_id,),
        ).fetchall()
    }


def matrix_shape(matrix: dict[tuple[int, int], str]) -> tuple[int, int]:
    if not matrix:
        return (0, 0)
    return (
        max(row_index for row_index, _ in matrix) + 1,
        max(col_index for _, col_index in matrix) + 1,
    )


def safe_json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def safe_json_list(value: str) -> list[Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def digest_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
