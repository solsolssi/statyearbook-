from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path

from app.core.numeric_text import parse_numeric_value
from app.db.connection import DB_PATH, DatabaseConnection, DatabaseRow, connect
from app.db.schema import init_db
from app.services.yearbook_reproduction_build_service import YearbookReproductionBuildService
from app.yearbook_data.relational_materializer import source_items, source_matrix


@dataclass(frozen=True)
class LedgerYearbookResult:
    report_id: int
    reproduction_run_id: int
    table_count: int
    cell_count: int


class LedgerYearbookService:
    """Publish a ledger materialization as an immutable annual-report snapshot."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

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
        with connect(self._db_path) as connection:
            init_db(connection)
            base = connection.execute(
                "SELECT * FROM annual_reports WHERE id = ?",
                (base_report_id,),
            ).fetchone()
            if base is None:
                raise ValueError("기준 연보를 찾을 수 없습니다.")
            existing = connection.execute(
                """
                SELECT id FROM annual_reports
                WHERE origin_kind = 'ledger_generated' AND base_report_id = ?
                  AND year = ? AND source_file_path = ? AND title = ?
                ORDER BY id DESC LIMIT 1
                """,
                (
                    base_report_id,
                    target_year,
                    f"ledger://batch/{source_batch_id}",
                    report_title,
                ),
            ).fetchone()
            if existing is not None:
                report_id = int(existing["id"])
                run = connection.execute(
                    """
                    SELECT id FROM yearbook_reproduction_runs
                    WHERE baseline_report_id = ? AND report_year = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (base_report_id, target_year),
                ).fetchone()
                return LedgerYearbookResult(
                    report_id=report_id,
                    reproduction_run_id=int(run["id"]) if run is not None else 0,
                    table_count=count_rows(
                        connection,
                        "SELECT COUNT(*) AS count FROM stat_tables WHERE report_id = ?",
                        (report_id,),
                    ),
                    cell_count=count_rows(
                        connection,
                        """
                        SELECT COUNT(*) AS count FROM stat_table_cells c
                        JOIN stat_tables t ON t.id = c.table_id
                        WHERE t.report_id = ?
                        """,
                        (report_id,),
                    ),
                )

        build = YearbookReproductionBuildService(self._db_path).run(
            report_id=base_report_id,
            report_year=target_year,
            target_data_year=target_year - 1,
        )
        imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source_path = f"ledger://batch/{source_batch_id}"
        file_hash = hashlib.sha256(
            f"{base_report_id}:{target_year}:{source_batch_id}:{mode}:{report_title}".encode()
        ).hexdigest()
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
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
                    overlays = generated_cells.get(source_table_id, {})
                    cell_count += copy_cells(
                        connection,
                        source_table_id=source_table_id,
                        target_table_id=new_table_id,
                        overlays=overlays,
                    )
                    status = str(result["status"]) if result is not None else "unavailable"
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
                new_table_count, new_cell_count = append_new_dataset_previews(
                    connection,
                    report_id=report_id,
                    source_batch_id=source_batch_id,
                    target_data_year=target_year - 1,
                    table_order_start=table_count + 1,
                    imported_at=imported_at,
                )
                table_count += new_table_count
                cell_count += new_cell_count
        return LedgerYearbookResult(
            report_id=report_id,
            reproduction_run_id=build.id,
            table_count=table_count,
            cell_count=cell_count,
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

    datasets = connection.execute(
        """
        SELECT id, external_id, title
        FROM statistical_datasets
        WHERE introduced_batch_id = ? AND status = 'active'
        ORDER BY id
        """,
        (source_batch_id,),
    ).fetchall()
    table_count = 0
    cell_count = 0
    for dataset in datasets:
        dataset_id = int(dataset["id"])
        items = source_items(connection, dataset_id)
        ordered_items = sorted(
            items.values(),
            key=lambda item: item.item_data_no,
        )
        source_rows = source_matrix(connection, dataset_id, target_data_year)
        if not ordered_items:
            continue
        matrix = [
            [item.full_name or item.item_name or str(item.item_data_no) for item in ordered_items]
        ]
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
        code = f"신규-{dataset['external_id']}"
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
                table_order_start + table_count,
                imported_at,
                str(dataset["external_id"]),
                "신규 통계입니다. 연보 표 번호와 레이아웃을 확정해 주세요.",
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
                "신규 원장 통계를 임시 레이아웃으로 표시했습니다. 표 번호와 배치를 확정해야 합니다.",
            ),
        )
        table_count += 1
        cell_count += len(rows)
    return table_count, cell_count
