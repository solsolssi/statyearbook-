from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from app.core.numeric_text import parse_numeric_value
from app.db.connection import DB_PATH, DatabaseConnection, DatabaseRow, connect
from app.db.schema import init_db
from app.services.yearbook_reproduction_build_service import YearbookReproductionBuildService
from app.services.yearbook_update_policy_service import YearbookUpdatePolicyService
from app.yearbook_data.relational_materializer import source_items, source_matrix
from app.yearbook_data.source_snapshots import (
    SourceSnapshotService,
    activate_source_snapshot,
)


@dataclass(frozen=True)
class LedgerYearbookResult:
    report_id: int
    reproduction_run_id: int
    source_snapshot_id: int
    table_count: int
    cell_count: int
    generated_table_count: int = 0
    review_table_count: int = 0
    deleted_table_count: int = 0
    new_table_count: int = 0


class LedgerYearbookService:
    """Publish a ledger materialization as an immutable annual-report snapshot."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def validate_request(self, *, base_report_id: int, target_year: int) -> None:
        with connect(self._db_path) as connection:
            init_db(connection)
            base = connection.execute(
                "SELECT year FROM annual_reports WHERE id = ?",
                (base_report_id,),
            ).fetchone()
        if base is None:
            raise ValueError("기준 연보를 찾을 수 없습니다.")
        expected_year = int(base["year"]) + 1
        if target_year != expected_year:
            raise ValueError(
                f"기준 연보 {base['year']}년의 다음 연보는 "
                f"{expected_year}년으로 생성해야 합니다."
            )

    def generate(
        self,
        *,
        base_report_id: int,
        target_year: int,
        source_batch_id: int,
        mode: str,
        title: str | None = None,
    ) -> LedgerYearbookResult:
        report_title = (title or "").strip() or f"{target_year} 원장 기반 통계연보"
        snapshot_service = SourceSnapshotService(self._db_path)
        with connect(self._db_path) as connection:
            init_db(connection)
            base = connection.execute(
                "SELECT * FROM annual_reports WHERE id = ?",
                (base_report_id,),
            ).fetchone()
            if base is None:
                raise ValueError("기준 연보를 찾을 수 없습니다.")
            expected_year = int(base["year"]) + 1
            if target_year != expected_year:
                raise ValueError(
                    f"기준 연보 {base['year']}년의 다음 연보는 "
                    f"{expected_year}년으로 생성해야 합니다."
                )
            with connection:
                snapshot = snapshot_service.create_child(
                    connection,
                    base_report_id=base_report_id,
                    source_batch_id=source_batch_id,
                    target_year=target_year - 1,
                )

        try:
            # A future edition must be generated solely from the selected
            # predecessor, its immutable source snapshot, the incremental
            # source batch, and persisted profiles.  A completed report for
            # the target year is intentionally never consulted here: it is a
            # comparison oracle after generation, not generation input.
            YearbookUpdatePolicyService(self._db_path).synchronize(
                report_id=base_report_id,
                source_snapshot_id=snapshot.id,
                edition_year=target_year,
                target_data_year=target_year - 1,
            )
            build = YearbookReproductionBuildService(self._db_path).run(
                report_id=base_report_id,
                report_year=target_year,
                target_data_year=target_year - 1,
                source_snapshot_id=snapshot.id,
            )
        except Exception:
            snapshot_service.discard_orphan(snapshot.id)
            raise
        imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source_path = f"ledger://snapshot/{snapshot.id}/batch/{source_batch_id}"
        file_hash = hashlib.sha256(
            f"{base_report_id}:{target_year}:{snapshot.id}:{source_batch_id}:{mode}:{report_title}".encode()
        ).hexdigest()
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection, activate_source_snapshot(connection, snapshot.id):
                cursor = connection.execute(
                    """
                    INSERT INTO annual_reports (
                        year, title, source_file_name, source_file_path, file_hash,
                        parse_warnings_json, imported_at, is_archived,
                        origin_kind, base_report_id
                    ) VALUES (?, ?, ?, ?, ?, '[]', ?, 0, 'ledger_generated', ?)
                    """,
                    (
                        target_year,
                        report_title,
                        report_title,
                        source_path,
                        file_hash,
                        imported_at,
                        base_report_id,
                    ),
                )
                report_id = int(cursor.lastrowid)
                snapshot_service.attach_report(
                    connection,
                    snapshot_id=snapshot.id,
                    report_id=report_id,
                )
                result_rows = connection.execute(
                    """
                    SELECT tr.*, rr.report_year
                    FROM yearbook_reproduction_table_results tr
                    JOIN yearbook_reproduction_runs rr ON rr.id = tr.run_id
                    WHERE tr.run_id = ?
                    """,
                    (build.id,),
                ).fetchall()
                results = {int(row["baseline_table_id"]): row for row in result_rows}
                generated_cells: dict[int, dict[tuple[int, int], str]] = {}
                for row in result_rows:
                    table_result_id = int(row["id"])
                    generated_cells[int(row["baseline_table_id"])] = {
                        (int(cell["row_index"]), int(cell["col_index"])): str(
                            cell["generated_value"] or ""
                        )
                        for cell in connection.execute(
                            """
                            SELECT row_index, col_index, generated_value
                            FROM yearbook_reproduction_cell_results
                            WHERE table_result_id = ?
                            """,
                            (table_result_id,),
                        ).fetchall()
                    }

                table_count = 0
                cell_count = 0
                for source_table in connection.execute(
                    """
                    SELECT * FROM stat_tables
                    WHERE report_id = ?
                    ORDER BY table_order, id
                    """,
                    (base_report_id,),
                ).fetchall():
                    source_table_id = int(source_table["id"])
                    result = results.get(source_table_id)
                    if result is not None and str(result["status"]) == "deleted":
                        continue
                    new_table_id = copy_table(
                        connection,
                        source_table,
                        report_id=report_id,
                        imported_at=imported_at,
                    )
                    table_count += 1
                    status = str(result["status"]) if result is not None else "unavailable"
                    successful_statuses = {
                        "exact",
                        "source_difference",
                        "empty",
                    }
                    overlays = (
                        generated_cells.get(source_table_id, {})
                        if status in successful_statuses
                        else {}
                    )
                    cell_count += copy_cells(
                        connection,
                        source_table_id=source_table_id,
                        target_table_id=new_table_id,
                        overlays=overlays,
                    )
                    message = str(result["error_message"] or "") if result is not None else ""
                    connection.execute(
                        """
                        INSERT INTO generated_report_table_status (
                            report_id, table_id, source_table_id,
                            generation_status, generation_message
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (report_id, new_table_id, source_table_id, status, message),
                    )
                appended_table_count, new_cell_count = append_new_dataset_previews(
                    connection,
                    report_id=report_id,
                    source_batch_id=source_batch_id,
                    target_data_year=target_year - 1,
                    table_order_start=table_count + 1,
                    imported_at=imported_at,
                )
                new_table_count = appended_table_count
                table_count += appended_table_count
                cell_count += new_cell_count
                generated_logical_count, review_logical_count = (
                    logical_generation_counts(connection, report_id)
                )
                manifest_deleted_logical_count = logical_deleted_count(
                    connection,
                    build.id,
                )
        return LedgerYearbookResult(
            report_id=report_id,
            reproduction_run_id=build.id,
            source_snapshot_id=snapshot.id,
            table_count=table_count,
            cell_count=cell_count,
            generated_table_count=generated_logical_count,
            review_table_count=review_logical_count,
            deleted_table_count=manifest_deleted_logical_count,
            new_table_count=new_table_count,
        )


def copy_table(
    connection: DatabaseConnection,
    source: DatabaseRow,
    *,
    report_id: int,
    imported_at: str,
) -> int:
    fields = (
        "code",
        "title",
        "title_en",
        "section_title",
        "section_title_en",
        "domain",
        "unit",
        "base_date",
        "section_file",
        "table_order",
        "cell_range",
        "note",
        "source",
        "raw_context",
        "parse_warnings_json",
    )
    cursor = connection.execute(
        f"""
        INSERT INTO stat_tables (
            report_id, {', '.join(fields)}, extracted_at
        ) VALUES (?, {', '.join('?' for _ in fields)}, ?)
        """,
        (report_id, *(source[field] for field in fields), imported_at),
    )
    return int(cursor.lastrowid)


def copy_cells(
    connection: DatabaseConnection,
    *,
    source_table_id: int,
    target_table_id: int,
    overlays: dict[tuple[int, int], str],
) -> int:
    source_cells = {
        (int(row["row_index"]), int(row["col_index"])): row
        for row in connection.execute(
            """
            SELECT * FROM stat_table_cells
            WHERE table_id = ?
            """,
            (source_table_id,),
        ).fetchall()
    }
    coordinates = sorted(set(source_cells) | set(overlays))
    rows = []
    header_limit = max(
        (
            int(row["row_index"])
            for row in source_cells.values()
            if bool(row["is_header"])
        ),
        default=-1,
    )
    for row_index, col_index in coordinates:
        source = source_cells.get((row_index, col_index))
        value = overlays.get(
            (row_index, col_index),
            str(source["text_value"] or "") if source is not None else "",
        )
        rows.append(
            (
                target_table_id,
                row_index,
                col_index,
                value,
                parse_numeric_value(value),
                int(source["is_header"]) if source is not None else int(row_index <= header_limit),
                str(source["footnote_marker"] or "") if source is not None else "",
                str(source["source_coordinate"] or "") if source is not None else "",
                str(source["text_color"] or "") if source is not None else "",
                str(source["parse_warnings_json"] or "[]") if source is not None else "[]",
            )
        )
    if rows:
        connection.executemany(
            """
            INSERT INTO stat_table_cells (
                table_id, row_index, col_index, text_value, numeric_value,
                is_header, footnote_marker, source_coordinate, text_color,
                parse_warnings_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def count_rows(
    connection: DatabaseConnection,
    sql: str,
    params: tuple[object, ...],
) -> int:
    row = connection.execute(sql, params).fetchone()
    return int(row["count"] or 0)


def logical_generation_counts(
    connection: DatabaseConnection,
    report_id: int,
) -> tuple[int, int]:
    review_statuses = {
        "unavailable",
        "source_missing",
        "recipe_required",
        "mapping_review",
        "new_table",
    }
    statuses_by_code: dict[str, set[str]] = {}
    for row in connection.execute(
        """
        SELECT table_row.code, status.generation_status
        FROM generated_report_table_status status
        JOIN stat_tables table_row ON table_row.id = status.table_id
        WHERE status.report_id = ?
        """,
        (report_id,),
    ).fetchall():
        statuses_by_code.setdefault(
            logical_table_code(str(row["code"])),
            set(),
        ).add(str(row["generation_status"]))
    review = sum(
        bool(statuses & review_statuses)
        for statuses in statuses_by_code.values()
    )
    return len(statuses_by_code) - review, review


def logical_deleted_count(
    connection: DatabaseConnection,
    reproduction_run_id: int,
) -> int:
    return len(
        {
            logical_table_code(str(row["code"]))
            for row in connection.execute(
                """
                SELECT table_row.code
                FROM yearbook_reproduction_table_results result
                JOIN stat_tables table_row
                  ON table_row.id = result.baseline_table_id
                WHERE result.run_id = ? AND result.status = 'deleted'
                """,
                (reproduction_run_id,),
            ).fetchall()
        }
    )


def logical_table_code(value: str) -> str:
    return re.sub(r"\s+표\s*\d+$", "", value).strip()


def append_new_dataset_previews(
    connection: DatabaseConnection,
    *,
    report_id: int,
    source_batch_id: int,
    target_data_year: int,
    table_order_start: int,
    imported_at: str,
) -> tuple[int, int]:
    """Expose newly introduced source statistics even before a layout is approved."""

    manifest_rows = connection.execute(
        """
        SELECT manifest.table_code, manifest.title, manifest.table_order,
               manifest.source_dataset_id,
               dataset.external_id, dataset.title AS dataset_title
        FROM yearbook_edition_manifest manifest
        LEFT JOIN statistical_datasets dataset
          ON dataset.id = manifest.source_dataset_id
        WHERE manifest.edition_year = ?
          AND manifest.lifecycle_status = 'new'
        ORDER BY manifest.table_order, manifest.id
        """,
        (target_data_year + 1,),
    ).fetchall()
    introduced_rows = connection.execute(
        """
        SELECT id, external_id, title
        FROM statistical_datasets
        WHERE introduced_batch_id = ? AND status = 'active'
        ORDER BY id
        """,
        (source_batch_id,),
    ).fetchall()
    candidates: list[dict[str, object]] = []
    included_dataset_ids: set[int] = set()
    for row in manifest_rows:
        dataset_id = (
            int(row["source_dataset_id"])
            if row["source_dataset_id"] is not None
            else 0
        )
        if dataset_id:
            included_dataset_ids.add(dataset_id)
        candidates.append(
            {
                "dataset_id": dataset_id,
                "external_id": str(row["external_id"] or ""),
                "title": str(row["title"] or row["dataset_title"] or row["table_code"]),
                "code": str(row["table_code"]),
                "table_order": int(row["table_order"] or 0),
                "manifest": True,
            }
        )
    for row in introduced_rows:
        dataset_id = int(row["id"])
        if dataset_id in included_dataset_ids:
            continue
        candidates.append(
            {
                "dataset_id": dataset_id,
                "external_id": str(row["external_id"] or ""),
                "title": str(row["title"] or row["external_id"]),
                "code": f"신규-{row['external_id']}",
                "table_order": 0,
                "manifest": False,
            }
        )
    table_count = 0
    cell_count = 0
    for dataset in candidates:
        dataset_id = int(dataset["dataset_id"])
        items = source_items(connection, dataset_id)
        ordered_items = sorted(
            items.values(),
            key=lambda item: item.item_data_no,
        )
        source_rows = source_matrix(connection, dataset_id, target_data_year)
        matrix = (
            [
                [
                    item.full_name or item.item_name or str(item.item_data_no)
                    for item in ordered_items
                ]
            ]
            if ordered_items
            else [["신규 통계 - 원장 연결 필요"]]
        )
        if ordered_items:
            matrix.extend(
                [
                    [
                        row.get(item.item_data_no).value
                        if row.get(item.item_data_no) is not None
                        else ""
                        for item in ordered_items
                    ]
                    for row in source_rows
                ]
            )
        code = str(dataset["code"])
        if connection.execute(
            "SELECT 1 FROM stat_tables WHERE report_id = ? AND code = ?",
            (report_id, code),
        ).fetchone() is not None:
            continue
        configured_order = int(dataset["table_order"] or 0)
        table_order = configured_order or table_order_start + table_count
        table = connection.execute(
            """
            INSERT INTO stat_tables (
                report_id, code, title, section_title, domain, table_order,
                extracted_at, source, note
            ) VALUES (?, ?, ?, ?, '신규 통계', ?, ?, ?, ?)
            """,
            (
                report_id,
                code,
                str(dataset["title"]),
                str(dataset["title"]),
                table_order,
                imported_at,
                str(dataset["external_id"]),
                (
                    "신규 통계 명세를 반영한 임시 레이아웃입니다. 행·열 배치를 확정해 주세요."
                    if bool(dataset["manifest"])
                    else "신규 통계입니다. 연보 표 번호와 레이아웃을 확정해 주세요."
                ),
            ),
        )
        table_id = int(table.lastrowid)
        rows = [
            (
                table_id,
                row_index,
                col_index,
                value,
                parse_numeric_value(value),
                int(row_index == 0),
            )
            for row_index, row in enumerate(matrix)
            for col_index, value in enumerate(row)
        ]
        connection.executemany(
            """
            INSERT INTO stat_table_cells (
                table_id, row_index, col_index, text_value, numeric_value, is_header
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.execute(
            """
            INSERT INTO generated_report_table_status (
                report_id, table_id, source_table_id,
                generation_status, generation_message
            ) VALUES (?, ?, NULL, 'new_table', ?)
            """,
            (
                report_id,
                table_id,
                (
                    "신규 연보 명세와 원장 통계를 임시 레이아웃으로 표시했습니다."
                    if bool(dataset["manifest"])
                    else "신규 원장 통계를 임시 레이아웃으로 표시했습니다. 표 번호와 배치를 확정해야 합니다."
                ),
            ),
        )
        table_count += 1
        cell_count += len(rows)
    return table_count, cell_count
