from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.core.numeric_text import parse_numeric_value
from app.db.connection import DB_PATH, DatabaseConnection, DatabaseRow, connect
from app.db.schema import init_db
from app.ingest.table_repairs import repair_local_government_sejong_eup_myeon_dong_column
from app.validation.models import (
    ValidationCell,
    ValidationCheckRecord,
    ValidationIssueRecord,
    ValidationTable,
)
from app.validation.result_repository import (
    merge_legacy_issues,
    refresh_run_issue_count,
    save_validation_results,
)


class ValidationRepository:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def latest_report(self) -> DatabaseRow | None:
        with connect(self._db_path) as connection:
            init_db(connection)
            return connection.execute(
                """
                SELECT *
                FROM annual_reports
                ORDER BY imported_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()

    def report(self, report_id: int) -> DatabaseRow | None:
        """Load one report explicitly.

        Automated imports must never validate whichever report happens to be
        newest at execution time. Keeping this lookup in the repository makes
        the report boundary explicit throughout the workflow.
        """

        with connect(self._db_path) as connection:
            init_db(connection)
            return connection.execute(
                "SELECT * FROM annual_reports WHERE id = ?",
                (report_id,),
            ).fetchone()

    def load_tables(
        self,
        report_id: int,
        table_ids: list[int] | None = None,
    ) -> list[ValidationTable]:
        with connect(self._db_path) as connection:
            init_db(connection)
            filters = ["report_id = ?"]
            params: list[object] = [report_id]
            if table_ids is not None:
                if not table_ids:
                    return []
                filters.append(f"id IN ({','.join('?' for _ in table_ids)})")
                params.extend(table_ids)
            table_rows = connection.execute(
                f"""
                SELECT id, report_id, code, title, unit, base_date, source, note
                FROM stat_tables
                WHERE {' AND '.join(filters)}
                ORDER BY table_order, id
                """,
                params,
            ).fetchall()

            return [self._load_table(connection, table_row) for table_row in table_rows]

    def save_run(
        self,
        *,
        report_id: int,
        rules_version: str,
        issues: list[ValidationIssueRecord],
        checks: list[ValidationCheckRecord] | None = None,
    ) -> int:
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        completed_at = started_at
        check_records = merge_legacy_issues(checks or [], issues)

        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                cursor = connection.execute(
                    """
                    INSERT INTO validation_runs (
                        report_id, rules_version, started_at, completed_at, issue_count
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (report_id, rules_version, started_at, completed_at, 0),
                )
                run_id = cursor.lastrowid

                save_validation_results(
                    connection,
                    run_id=int(run_id),
                    results=check_records,
                )
                refresh_run_issue_count(connection, run_id=int(run_id))

        return int(run_id)

    def _load_table(
        self,
        connection: DatabaseConnection,
        table_row: DatabaseRow,
    ) -> ValidationTable:
        cells = connection.execute(
            """
            SELECT row_index, col_index, text_value, numeric_value, is_header
            FROM stat_table_cells
            WHERE table_id = ?
            ORDER BY row_index, col_index
            """,
            (table_row["id"],),
        ).fetchall()
        validation_cells = validation_cells_from_rows(str(table_row["code"]), cells)

        return ValidationTable(
            id=table_row["id"],
            report_id=table_row["report_id"],
            code=table_row["code"],
            title=table_row["title"],
            unit=table_row["unit"],
            base_date=table_row["base_date"],
            source=table_row["source"],
            note=table_row["note"],
            cells=validation_cells,
        )


def validation_cells_from_rows(
    table_code: str,
    cells: list[DatabaseRow],
) -> list[ValidationCell]:
    if table_code != "4-1-9 표4" or not cells:
        return [
            ValidationCell(
                row_index=cell["row_index"],
                col_index=cell["col_index"],
                text_value=cell["text_value"],
                numeric_value=cell["numeric_value"],
                is_header=bool(cell["is_header"]),
            )
            for cell in cells
        ]

    max_row = max(cell["row_index"] for cell in cells)
    max_col = max(cell["col_index"] for cell in cells)
    matrix = [["" for _ in range(max_col + 1)] for _ in range(max_row + 1)]
    footnote_matrix = [["" for _ in range(max_col + 1)] for _ in range(max_row + 1)]
    header_rows = {int(cell["row_index"]) for cell in cells if cell["is_header"]}
    for cell in cells:
        matrix[cell["row_index"]][cell["col_index"]] = cell["text_value"] or ""

    repair_local_government_sejong_eup_myeon_dong_column(matrix, footnote_matrix)

    return [
        ValidationCell(
            row_index=row_index,
            col_index=col_index,
            text_value=value,
            numeric_value=parse_numeric_value(value),
            is_header=row_index in header_rows,
        )
        for row_index, row in enumerate(matrix)
        for col_index, value in enumerate(row)
    ]
