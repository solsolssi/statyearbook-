from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ParsedCell:
    row_index: int
    col_index: int
    text_value: str
    numeric_value: float | None
    is_header: bool
    footnote_marker: str = ""
    source_coordinate: str = ""
    text_color: str = ""
    parse_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedTable:
    """Parser-neutral table contract shared by HWPX, Markdown and Excel."""

    code: str
    title: str
    matrix: list[list[str]]
    title_en: str = ""
    section_title: str = ""
    section_title_en: str = ""
    domain: str = "통계"
    unit: str = ""
    base_date: str = ""
    section_file: str = ""
    table_order: int = 0
    note: str = ""
    source: str = ""
    raw_context: str = ""
    header_count: int = 1
    footnote_matrix: list[list[str]] = field(default_factory=list)
    cells: tuple[ParsedCell, ...] = ()
    parse_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedReport:
    year: int
    title: str
    source_path: Path
    tables: tuple[ParsedTable, ...]
    source_file_name: str = ""
    file_hash: str = ""
    parse_warnings: tuple[str, ...] = ()
