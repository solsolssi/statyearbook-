from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path

from app.core.numeric_text import parse_numeric_value
from app.domain.parsed import ParsedCell, ParsedReport, ParsedTable


class ReportParseError(ValueError):
    pass


SUPPORTED_PARSERS = {"xlsx", "hwpx", "markdown"}


def parse_report(
    source_path: Path,
    *,
    source_type: str,
    year: int,
    title: str,
    source_file_name: str | None = None,
    file_hash: str = "",
) -> ParsedReport:
    if source_type not in SUPPORTED_PARSERS:
        supported = ", ".join(sorted(SUPPORTED_PARSERS))
        raise ReportParseError(
            f"등록되지 않은 가져오기 형식입니다: {source_type}. 지원 형식: {supported}"
        )

    path = source_path.expanduser().resolve()
    tables = tuple(
        normalize_parsed_table(table)
        for table in parse_tables(path, source_type=source_type, year=year)
    )
    report = ParsedReport(
        year=year,
        title=title,
        source_path=path,
        source_file_name=source_file_name or path.name,
        file_hash=file_hash or file_digest(path),
        tables=tables,
    )
    validate_parsed_report(report)
    return report


def parse_tables(
    source_path: Path,
    *,
    source_type: str,
    year: int | None = None,
) -> list[ParsedTable]:
    # Lazy imports keep the parser-neutral registry independent from each
    # format adapter and avoid package import cycles.
    if source_type == "xlsx":
        from app.ingest.excel_importer import parse_excel

        return parse_excel(source_path)
    if source_type == "hwpx":
        from app.ingest.hwpx_importer import parse_hwpx, prepare_hwpx_import_tables

        return prepare_hwpx_import_tables(parse_hwpx(source_path), report_year=year)
    if source_type == "markdown":
        from app.ingest.markdown_importer import (
            parse_markdown,
            prepare_markdown_import_tables,
        )

        return prepare_markdown_import_tables(parse_markdown(source_path))
    raise ReportParseError(f"등록되지 않은 가져오기 형식입니다: {source_type}")


def normalize_parsed_table(table: ParsedTable) -> ParsedTable:
    width = max((len(row) for row in table.matrix), default=0)
    matrix = [
        [str(value or "") for value in [*row, *([""] * (width - len(row)))]]
        for row in table.matrix
    ]
    warnings = list(table.parse_warnings)
    if any(len(row) != width for row in table.matrix):
        warnings.append("행별 열 개수가 달라 빈 셀로 정규화했습니다.")

    existing_cells = {
        (cell.row_index, cell.col_index): cell
        for cell in table.cells
    }
    cells: list[ParsedCell] = []
    for row_index, row in enumerate(matrix):
        footnotes = (
            table.footnote_matrix[row_index]
            if row_index < len(table.footnote_matrix)
            else []
        )
        for col_index, value in enumerate(row):
            existing = existing_cells.get((row_index, col_index))
            cells.append(
                ParsedCell(
                    row_index=row_index,
                    col_index=col_index,
                    text_value=value,
                    numeric_value=parse_numeric_value(value),
                    is_header=row_index < table.header_count,
                    footnote_marker=(
                        existing.footnote_marker
                        if existing is not None
                        else (footnotes[col_index] if col_index < len(footnotes) else "")
                    ),
                    source_coordinate=(
                        existing.source_coordinate
                        if existing is not None
                        else spreadsheet_coordinate(row_index, col_index)
                    ),
                    text_color=existing.text_color if existing is not None else "",
                    parse_warnings=existing.parse_warnings if existing is not None else (),
                )
            )
    return replace(
        table,
        matrix=matrix,
        cells=tuple(cells),
        parse_warnings=tuple(dict.fromkeys(warnings)),
    )


def validate_parsed_report(report: ParsedReport) -> None:
    if not report.tables:
        raise ReportParseError("원본 파일에서 저장 가능한 통계표를 찾지 못했습니다.")

    codes: set[str] = set()
    errors: list[str] = []
    for table_index, table in enumerate(report.tables, start=1):
        prefix = table.code or f"{table_index}번째 표"
        width = max((len(row) for row in table.matrix), default=0)
        if not table.code.strip():
            errors.append(f"{prefix}: 표 번호가 없습니다.")
        elif table.code in codes:
            errors.append(f"{prefix}: 동일한 표 번호가 중복되었습니다.")
        codes.add(table.code)
        if not table.title.strip():
            errors.append(f"{prefix}: 표 제목이 없습니다.")
        if not table.matrix or width < 2:
            errors.append(f"{prefix}: 2열 이상의 표 데이터가 없습니다.")
        if table.header_count < 0 or table.header_count > len(table.matrix):
            errors.append(f"{prefix}: 헤더 행 수가 표 범위를 벗어났습니다.")
        positions = {(cell.row_index, cell.col_index) for cell in table.cells}
        if len(positions) != len(table.cells):
            errors.append(f"{prefix}: 동일한 셀 좌표가 중복되었습니다.")
        if table.cells and len(table.cells) != len(table.matrix) * width:
            errors.append(f"{prefix}: 셀 좌표와 표 행렬의 크기가 일치하지 않습니다.")

    if errors:
        preview = "\n".join(errors[:20])
        suffix = f"\n외 {len(errors) - 20}건" if len(errors) > 20 else ""
        raise ReportParseError(f"파싱 결과 구조 검증에 실패했습니다.\n{preview}{suffix}")


def spreadsheet_coordinate(row_index: int, col_index: int) -> str:
    current = col_index + 1
    column = ""
    while current:
        current, remainder = divmod(current - 1, 26)
        column = chr(65 + remainder) + column
    return f"{column}{row_index + 1}"


def file_digest(source_path: Path) -> str:
    digest = hashlib.sha256()
    with source_path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
