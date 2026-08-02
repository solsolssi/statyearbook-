from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path

from app.core.numeric_text import parse_numeric_value
from app.db.connection import DB_PATH, DatabaseConnection, connect
from app.db.schema import init_db
from app.domain.parsed import ParsedReport, ParsedTable


# Compatibility alias for importers and external scripts. New code should use
# ParsedTable, which is the parser-neutral domain contract.
ImportedTable = ParsedTable


@dataclass(frozen=True)
class ImportResult:
    report_id: int
    table_count: int
    cell_count: int


class ReportImportRepository:
    """Persist parser-neutral annual report tables in one transaction."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def replace_report(
        self,
        *,
        source_path: Path,
        source_file_name: str | None = None,
        year: int,
        title: str,
        tables: list[ImportedTable],
        archive_previous_same_title: bool = False,
    ) -> ImportResult:
        report = ParsedReport(
            year=year,
            title=title,
            source_path=source_path,
            source_file_name=source_file_name or source_path.name,
            file_hash=file_digest(source_path),
            tables=tuple(tables),
        )
        return self.replace_parsed_report(
            report,
            archive_previous_same_title=archive_previous_same_title,
        )

    def replace_parsed_report(
        self,
        report: ParsedReport,
        *,
        persisted_source_path: str | None = None,
        archive_previous_same_title: bool = False,
        force_new: bool = False,
        origin_kind: str = "uploaded",
        base_report_id: int | None = None,
    ) -> ImportResult:
        valid_tables = [
            table
            for table in report.tables
            if table.matrix and max((len(row) for row in table.matrix), default=0) >= 2
        ]
        if not valid_tables:
            raise ValueError("원본 파일에서 저장 가능한 통계표를 찾지 못했습니다.")

        imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        source_hash = report.file_hash or file_digest(report.source_path)
        if force_new:
            source_hash = hashlib.sha256(
                f"{source_hash}:{imported_at}:{report.year}:{report.title}".encode()
            ).hexdigest()
        table_count = 0
        cell_count = 0

        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                existing_report = connection.execute(
                    "SELECT id FROM annual_reports WHERE file_hash = ?",
                    (source_hash,),
                ).fetchone()
                if existing_report is not None:
                    # Exact input is idempotent. Reuse the prior report rather
                    # than deleting its tables and forcing the database to inspect
                    # every historical validation record that references them.
                    report_id = int(existing_report["id"])
                    connection.execute(
                        "UPDATE annual_reports SET is_archived = 0 WHERE id = ?",
                        (report_id,),
                    )
                    return ImportResult(
                        report_id=report_id,
                        table_count=table_count_for_report(connection, report_id),
                        cell_count=cell_count_for_report(connection, report_id),
                    )

                if archive_previous_same_title:
                    connection.execute(
                        "UPDATE annual_reports SET is_archived = 1 WHERE year = ? AND title = ?",
                        (report.year, report.title),
                    )
                cursor = connection.execute(
                    """
                    INSERT INTO annual_reports (
                        year, title, source_file_name, source_file_path, file_hash,
                        parse_warnings_json, imported_at, origin_kind, base_report_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        report.year,
                        report.title,
                        report.source_file_name or report.source_path.name,
                        persisted_source_path or str(report.source_path),
                        source_hash,
                        json.dumps(report.parse_warnings, ensure_ascii=False),
                        imported_at,
                        origin_kind,
                        base_report_id,
                    ),
                )
                report_id = int(cursor.lastrowid)

                for table in valid_tables:
                    width = max((len(row) for row in table.matrix), default=0)
                    table_cursor = connection.execute(
                        """
                        INSERT INTO stat_tables (
                            report_id, code, title, title_en, section_title, section_title_en,
                            domain, unit, base_date, section_file, table_order, cell_range,
                            note, source, extracted_at, raw_context, parse_warnings_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            report_id,
                            table.code,
                            table.title,
                            table.title_en,
                            table.section_title or table.title,
                            table.section_title_en or table.title_en,
                            table.domain,
                            table.unit,
                            table.base_date,
                            table.section_file,
                            table.table_order,
                            excel_range(width, len(table.matrix)),
                            table.note,
                            table.source,
                            imported_at,
                            table.raw_context[:5000],
                            json.dumps(table.parse_warnings, ensure_ascii=False),
                        ),
                    )
                    table_id = int(table_cursor.lastrowid)
                    table_count += 1

                    parsed_cells = {
                        (cell.row_index, cell.col_index): cell
                        for cell in table.cells
                    }
                    for row_index, source_row in enumerate(table.matrix):
                        row = [*source_row, *([""] * (width - len(source_row)))]
                        footnotes = (
                            table.footnote_matrix[row_index]
                            if row_index < len(table.footnote_matrix)
                            else []
                        )
                        for col_index, value in enumerate(row):
                            parsed_cell = parsed_cells.get((row_index, col_index))
                            footnote = footnotes[col_index] if col_index < len(footnotes) else ""
                            connection.execute(
                                """
                                INSERT INTO stat_table_cells (
                                    table_id, row_index, col_index, text_value, numeric_value,
                                    is_header, footnote_marker, source_coordinate, text_color,
                                    parse_warnings_json
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    table_id,
                                    row_index,
                                    col_index,
                                    value,
                                    (
                                        parsed_cell.numeric_value
                                        if parsed_cell is not None
                                        else parse_numeric_value(value)
                                    ),
                                    (
                                        int(parsed_cell.is_header)
                                        if parsed_cell is not None
                                        else (1 if row_index < table.header_count else 0)
                                    ),
                                    (
                                        parsed_cell.footnote_marker
                                        if parsed_cell is not None
                                        else footnote
                                    ),
                                    parsed_cell.source_coordinate if parsed_cell is not None else "",
                                    parsed_cell.text_color if parsed_cell is not None else "",
                                    json.dumps(
                                        parsed_cell.parse_warnings if parsed_cell is not None else (),
                                        ensure_ascii=False,
                                    ),
                                ),
                            )
                            cell_count += 1

        return ImportResult(report_id=report_id, table_count=table_count, cell_count=cell_count)


def file_digest(source_path: Path) -> str:
    digest = hashlib.sha256()
    with source_path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def table_count_for_report(connection: DatabaseConnection, report_id: int) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM stat_tables WHERE report_id = ?",
        (report_id,),
    ).fetchone()
    return int(row["count"])


def cell_count_for_report(connection: DatabaseConnection, report_id: int) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM stat_table_cells cells
        JOIN stat_tables tables ON tables.id = cells.table_id
        WHERE tables.report_id = ?
        """,
        (report_id,),
    ).fetchone()
    return int(row["count"])


def excel_range(width: int, height: int) -> str:
    current = width
    column = ""
    while current:
        current, remainder = divmod(current - 1, 26)
        column = chr(65 + remainder) + column
    return f"A1:{column}{height}"
