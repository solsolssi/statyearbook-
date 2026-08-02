from __future__ import annotations

import argparse
from dataclasses import dataclass, field, replace
from pathlib import Path
import re
from typing import Iterable
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from app.core.contact_metadata import clean_source_text
from app.db.connection import DB_PATH
from app.core.numeric_text import parse_numeric_value
from app.ingest.anomaly import annotate_adjacent_duplicate_tables
from app.ingest.cell_text import footnote_markers_from_texts, split_cell_text
from app.ingest.repository import ImportedTable, ReportImportRepository
from app.ingest.table_repairs import repair_region_split_rows
from app.validation.models import restore_hyphenated_line_breaks


NUMERIC_TABLE_CODE_PATTERN = r"(?:[1-9]|1[0-9])-\d{1,2}-\d{1,2}(?:-\d{1,2})?"
APPENDIX_TABLE_CODE_PATTERN = r"부록\s*\d+(?:-\d+)?"
TABLE_CODE_RE = re.compile(
    rf"(?<![\d-])(?:"
    # A numeric title can immediately follow a four-part code in HWPX
    # (for example, ``8-1-1-330년경과...`` means ``8-1-1-3``).
    rf"(?:[1-9]|1[0-9])-\d{{1,2}}-\d{{1,2}}-\d{{1,2}}(?=\d{{2,4}}년)"
    rf"|{NUMERIC_TABLE_CODE_PATTERN}(?![-\d])"
    rf"|{APPENDIX_TABLE_CODE_PATTERN}(?![-\d])"
    rf")"
)
ENGLISH_TITLE_CHARS = r"A-Za-z0-9 ,:&/().%\[\]·･+=\-'’‘′ʼ~"
ENGLISH_TITLE_RE = re.compile(
    rf"(?<![A-Za-z0-9])([A-Za-z][{ENGLISH_TITLE_CHARS}]{{2,}}|\d+-[A-Za-z][{ENGLISH_TITLE_CHARS}]{{2,}})$"
)
ENGLISH_ONLY_RE = re.compile(rf"(?=[{ENGLISH_TITLE_CHARS}]*[A-Za-z])[{ENGLISH_TITLE_CHARS}]+")
KOREAN_HEADER_LABELS = {
    "구분",
    "분류",
    "지역",
    "연도",
    "기관",
    "기관명",
    "항목",
    "유형",
    "성별",
    "직급",
    "계급",
}
ENGLISH_HEADER_LABELS = {
    "classification",
    "region",
    "year",
    "organization",
    "institution",
    "item",
    "type",
    "category",
    "sex",
    "grade",
}
HEADER_LABEL_PAIRS = (
    ("구분", "classification"),
    ("분류", "classification"),
    ("지역", "region"),
    ("연도", "year"),
    ("기관", "organization"),
    ("기관명", "institution"),
    ("항목", "item"),
    ("유형", "type"),
    ("성별", "sex"),
    ("직급", "grade"),
    ("계급", "grade"),
)

DOMAIN_BY_CHAPTER = {
    "1": "조직",
    "2": "행정관리",
    "3": "전자정부",
    "4": "지방행정",
    "5": "지방재정",
    "6": "안전",
    "7": "재난관리",
    "8": "민방위",
    "9": "비상대비",
}

CURATED_SOURCE_BY_CODE = {
    # 부록 3 is mapped to the confirmed ledger dataset M214663130943978.
    # In the 2026 HWPX/MD, a page-break contact is also collected while the
    # long appendix table continues across pages.  Keep the confirmed ledger
    # contact when both are present, but do not force this value when a future
    # year provides a different source.
    "부록 3": ("혁신행정담당관실 주무관 허재은 (044-205-1439)",),
}


@dataclass
class TablePart:
    section_file: str
    matrix: list[list[str]]
    raw_text: str
    footnote_matrix: list[list[str]] = field(default_factory=list)


@dataclass
class LogicalTable:
    code: str
    title: str
    title_en: str
    section_title: str
    section_title_en: str
    section_file: str
    table_order: int
    parts: list[TablePart] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    metadata_context: str = ""


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def visible_paragraphs(element: ET.Element) -> Iterable[ET.Element]:
    """Yield visible paragraphs while ignoring HWPX memo field payloads."""

    if local_name(element.tag) == "fieldBegin":
        return
    if local_name(element.tag) == "p":
        yield element
        return
    for child in element:
        yield from visible_paragraphs(child)


def visible_text_fragments(element: ET.Element) -> Iterable[str]:
    """Yield text nodes that are rendered as document content.

    ``Element.itertext()`` also includes field parameters and memo bodies.
    Those values were previously concatenated into table codes and titles.
    """

    if local_name(element.tag) == "fieldBegin":
        return
    if local_name(element.tag) == "t":
        yield "".join(element.itertext())
        return
    for child in element:
        yield from visible_text_fragments(child)


def join_text_fragments(fragments: Iterable[str]) -> str:
    result = ""
    previous_raw = ""
    for raw_fragment in fragments:
        fragment = re.sub(r"\s+", " ", raw_fragment)
        cleaned = fragment.strip()
        if not cleaned:
            continue

        separator = ""
        if result:
            previous_char = result[-1]
            current_char = cleaned[0]
            boundary_had_space = bool(
                previous_raw and (previous_raw[-1:].isspace() or fragment[:1].isspace())
            )
            crosses_korean_latin_boundary = bool(
                (re.match(r"[가-힣]", previous_char) and re.match(r"[A-Za-z]", current_char))
                or (re.match(r"[A-Za-z]", previous_char) and re.match(r"[가-힣]", current_char))
            )
            continues_hyphenated_code = current_char == "-" and previous_char.isdigit()
            if (boundary_had_space or crosses_korean_latin_boundary) and not continues_hyphenated_code:
                separator = " "

        result += separator + cleaned
        previous_raw = fragment
    return result


def element_text(element: ET.Element) -> str:
    paragraphs = [
        join_text_fragments(visible_text_fragments(paragraph))
        for paragraph in visible_paragraphs(element)
    ]
    visible = [paragraph for paragraph in paragraphs if paragraph]
    if visible:
        return "\n".join(visible)
    return join_text_fragments(visible_text_fragments(element))


def split_bilingual(text: str) -> tuple[str, str]:
    cleaned = re.sub(r"\s+", " ", text).replace("\\~", "~").replace("᭼", "･").strip(" :;?")
    if not cleaned:
        return "", ""

    if ENGLISH_ONLY_RE.fullmatch(cleaned):
        return "", cleaned

    match = ENGLISH_TITLE_RE.search(cleaned)
    if match and match.start() > 0:
        prefix = cleaned[: match.start()]
        if prefix.endswith("(") and re.fullmatch(
            r"(?:[A-Za-z]/[A-Za-z]|[A-Za-z](?:[+\-][A-Za-z])+|[A-Za-z]=[A-Za-z](?:[+\-][A-Za-z])+)\)",
            match.group(1),
        ):
            return cleaned, ""
        return cleaned[: match.start()].strip(), match.group(1).strip()

    return cleaned, ""


def separate_bilingual_lines(text: str) -> str:
    separated: list[str] = []
    for line in text.splitlines():
        korean, english = split_bilingual(line)
        if korean and english:
            separated.extend((korean, english))
        elif korean or english:
            separated.append(korean or english)
    return "\n".join(separated)


def normalize_table_code(value: str) -> str:
    compact = re.sub(r"\s+", "", value)
    if compact.startswith("부록"):
        return f"부록 {compact.removeprefix('부록')}"
    return compact


def is_range_marker(text: str, match: re.Match[str]) -> bool:
    return bool(re.match(r"\s*[~∼]\s*\d+", text[match.end() :]))


def clean_title_context(text: str) -> str:
    cleaned = re.sub(
        rf"{NUMERIC_TABLE_CODE_PATTERN}\s*[~∼]\s*\d+",
        " ",
        text,
    )
    cleaned = re.sub(r"데이터\s*미입력(?:\([^)]*\))?", " ", cleaned)
    cleaned = re.sub(r"[（(]\s*영문\s*[)）]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_title_block(text: str) -> tuple[str, str, str, str, str] | None:
    matches = [match for match in TABLE_CODE_RE.finditer(text) if not is_range_marker(text, match)]
    if not matches:
        return None

    table_match = matches[-1]
    code = normalize_table_code(table_match.group(0))
    title_ko, title_en = split_bilingual(clean_title_context(text[table_match.end() :]))

    section_ko = ""
    section_en = ""
    if len(matches) >= 2:
        section_text = clean_title_context(text[matches[-2].end() : table_match.start()])
        section_ko, section_en = split_bilingual(section_text)

    return code, title_ko or code, title_en, section_ko, section_en


def cell_position(cell: ET.Element) -> tuple[int, int, int, int]:
    addr = next((item for item in cell.iter() if local_name(item.tag) == "cellAddr"), None)
    span = next((item for item in cell.iter() if local_name(item.tag) == "cellSpan"), None)

    row = int((addr.attrib if addr is not None else {}).get("rowAddr", "0"))
    col = int((addr.attrib if addr is not None else {}).get("colAddr", "0"))
    row_span = int((span.attrib if span is not None else {}).get("rowSpan", "1"))
    col_span = int((span.attrib if span is not None else {}).get("colSpan", "1"))
    return row, col, row_span, col_span


def superscript_char_ids(header_xml: bytes) -> set[str]:
    root = ET.fromstring(header_xml)
    return {
        element.attrib["id"]
        for element in root.iter()
        if local_name(element.tag) == "charPr"
        and element.attrib.get("id")
        and any(local_name(child.tag) == "supscript" for child in element)
    }


def cell_text_with_footnote(
    cell: ET.Element,
    superscript_ids: set[str],
) -> tuple[str, str]:
    text = element_text(cell)
    # HWPX sometimes stores the expression inside parentheses in a separate
    # paragraph, for example ``계(\nA+B)``. It is one visible header label.
    text = re.sub(r"\([ \t]*\n[ \t]*", "(", text)
    text = re.sub(r"[ \t]*\n[ \t]*\)", ")", text)
    markers: list[str] = []
    for run in (item for item in cell.iter() if local_name(item.tag) == "run"):
        if run.attrib.get("charPrIDRef") not in superscript_ids:
            continue
        marker = element_text(run).replace(" ", "")
        if re.fullmatch(r"\d+\)", marker) and marker not in markers:
            markers.append(marker)

    for marker in markers:
        text = re.sub(
            rf"[ \t]*{re.escape(marker)}[ \t]*(?=\n|$|\()",
            "",
            text,
        ).strip()
    return separate_bilingual_lines(text), " ".join(markers)


def table_matrix_with_footnotes(
    table: ET.Element,
    superscript_ids: set[str],
) -> tuple[list[list[str]], list[list[str]]]:
    cells: list[tuple[str, str, int, int, int, int]] = []
    max_row = 0
    max_col = 0

    for row in [item for item in list(table) if local_name(item.tag) == "tr"]:
        for cell in [item for item in list(row) if local_name(item.tag) == "tc"]:
            row_index, col_index, row_span, col_span = cell_position(cell)
            text, footnote_marker = cell_text_with_footnote(cell, superscript_ids)
            cells.append((text, footnote_marker, row_index, col_index, row_span, col_span))
            max_row = max(max_row, row_index + row_span)
            max_col = max(max_col, col_index + col_span)

    matrix = [["" for _ in range(max_col)] for _ in range(max_row)]
    footnote_matrix = [["" for _ in range(max_col)] for _ in range(max_row)]
    for text, footnote_marker, row_index, col_index, row_span, col_span in cells:
        for target_row in range(row_index, row_index + row_span):
            for target_col in range(col_index, col_index + col_span):
                if target_row < max_row and target_col < max_col and not matrix[target_row][target_col]:
                    matrix[target_row][target_col] = text if target_col == col_index else ""
                    footnote_matrix[target_row][target_col] = footnote_marker if target_col == col_index else ""

    return matrix, footnote_matrix


def table_matrix(table: ET.Element) -> list[list[str]]:
    matrix, _ = table_matrix_with_footnotes(table, set())
    return matrix


def is_data_table(matrix: list[list[str]]) -> bool:
    row_count = len(matrix)
    col_count = max((len(row) for row in matrix), default=0)
    non_empty_count = sum(1 for row in matrix for cell in row if cell)
    if row_count >= 3 and col_count >= 2 and non_empty_count >= 6:
        return True
    # A one-year table can consist of exactly one header and one data row.
    # Requiring three rows silently discarded these small continuation parts.
    return (
        row_count == 2
        and col_count >= 2
        and non_empty_count >= 4
        and any(looks_like_data_row(row) for row in matrix)
    )


def is_title_table(matrix: list[list[str]], text: str) -> bool:
    row_count = len(matrix)
    col_count = max((len(row) for row in matrix), default=0)
    return bool(parse_title_block(text)) and col_count == 1 and row_count <= 6


def append_unique(target: list[str], value: str) -> None:
    cleaned = clean_source_text(value)
    if cleaned and cleaned not in target:
        target.append(cleaned)


def source_normalization_code(code: str) -> str:
    return re.sub(r"\s+표\d+$", "", code.strip())


def normalize_table_sources(code: str, sources: list[str]) -> list[str]:
    cleaned_sources: list[str] = []
    for source in sources:
        append_unique(cleaned_sources, source)

    curated_sources = CURATED_SOURCE_BY_CODE.get(source_normalization_code(code))
    if not curated_sources:
        return cleaned_sources

    matched_curated_sources = [
        source for source in curated_sources if source in cleaned_sources
    ]
    if matched_curated_sources:
        return matched_curated_sources
    return cleaned_sources


def parse_hwpx(source_path: Path) -> list[LogicalTable]:
    tables: list[LogicalTable] = []
    current: LogicalTable | None = None
    title_context_by_code: dict[str, tuple[str, str]] = {}

    with ZipFile(source_path) as archive:
        superscript_ids = superscript_char_ids(archive.read("Contents/header.xml"))
        section_names = [
            name
            for name in archive.namelist()
            if re.fullmatch(r"Contents/section[1-9]\.xml", name)
        ]

        for section_name in sorted(section_names):
            table_depth = 0
            for event, element in ET.iterparse(archive.open(section_name), events=("start", "end")):
                tag_name = local_name(element.tag)

                if event == "start" and tag_name == "tbl":
                    table_depth += 1
                    continue

                if event == "end" and tag_name == "tbl":
                    if table_depth == 1:
                        matrix, footnote_matrix = table_matrix_with_footnotes(element, superscript_ids)
                        text = element_text(element)
                        title = parse_title_block(text)

                        if title and is_title_table(matrix, text):
                            section_title, section_title_en = resolve_title_section(
                                title,
                                title_context_by_code,
                            )
                            current = LogicalTable(
                                code=title[0],
                                title=title[1],
                                title_en=title[2],
                                section_title=section_title,
                                section_title_en=section_title_en,
                                section_file=section_name,
                                table_order=len(tables) + 1,
                            )
                            remember_title_context(title, title_context_by_code)
                            tables.append(current)
                        elif current and is_data_table(matrix):
                            for row in matrix:
                                if is_embedded_source_row(row):
                                    append_unique(
                                        current.sources,
                                        " ".join(cell.strip() for cell in row if cell.strip()),
                                    )
                            current.parts.append(
                                TablePart(
                                    section_file=section_name,
                                    matrix=matrix,
                                    raw_text=text,
                                    footnote_matrix=footnote_matrix,
                                )
                            )

                    table_depth -= 1
                    element.clear()
                    continue

                if event == "end" and tag_name == "p" and table_depth == 0:
                    text = element_text(element)
                    if current and text:
                        if text.startswith("#") or is_note_continuation_text(text, current.notes):
                            append_unique(current.notes, text)
                        elif is_metadata_text(text):
                            current.metadata_context = " ".join(
                                value
                                for value in (current.metadata_context, text)
                                if value
                            )
                        elif text.startswith("*") or "주무관" in text or "사무관" in text:
                            append_unique(current.sources, text)
                        elif "출처" in text:
                            append_unique(current.notes, text)
                    element.clear()

    return [table for table in tables if table.parts]


def immediate_parent_table_code(code: str) -> str:
    base_code = code_without_part_suffix(code)
    if base_code.startswith("부록 "):
        match = re.match(r"^(부록\s+\d+)-\d+$", base_code)
        return match.group(1) if match else ""
    parts = base_code.split("-")
    return "-".join(parts[:-1]) if len(parts) > 1 else ""


def code_without_part_suffix(code: str) -> str:
    return re.sub(r"\s+표\s*\d+$", "", code).strip()


def metadata_unit_key(unit: str) -> str:
    return re.sub(r"\s+", "", unit).strip()


def metadata_inheritance_code(code: str) -> str:
    base_code = code_without_part_suffix(code)
    if base_code != code:
        return base_code
    return immediate_parent_table_code(code)


def default_base_date_for_report_year(report_year: int | None) -> str:
    if report_year is None:
        return ""
    return f"{report_year - 1}. 12. 31."


def resolve_title_section(
    title: tuple[str, str, str, str, str],
    title_context_by_code: dict[str, tuple[str, str]],
) -> tuple[str, str]:
    parent_context = title_context_by_code.get(
        immediate_parent_table_code(title[0]),
        ("", ""),
    )
    return title[3] or parent_context[0], title[4] or parent_context[1]


def remember_title_context(
    title: tuple[str, str, str, str, str],
    title_context_by_code: dict[str, tuple[str, str]],
) -> None:
    title_context_by_code[title[0]] = (title[1], title[2])
    parent_code = immediate_parent_table_code(title[0])
    if title[3] and parent_code:
        title_context_by_code[parent_code] = (title[3], title[4])


def extract_unit_and_base_date(raw_text: str) -> tuple[str, str]:
    unit = ""
    base_date = ""

    unit_match = re.search(r"단위\s*:\s*([^)（]+)", raw_text)
    if unit_match:
        unit = unit_match.group(1).strip()

    date_match = re.search(r"(\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?)\s*기준", raw_text)
    if date_match:
        base_date = normalize_base_date(date_match.group(1))
    else:
        period_match = reference_period_match(raw_text)
        if period_match:
            base_date = normalize_reference_period(period_match.group(0))

    return unit, base_date


def reference_period_match(raw_text: str) -> re.Match[str] | None:
    return re.search(
        r"\[\s*제\s*\d+\s*기\s*[:：]\s*[’']?\d{2,4}\s*\.\s*\d{1,2}\s*\.?\s*[~∼-]\s*[’']?\d{2,4}\s*\.\s*\d{1,2}\s*\.?\s*\]",
        raw_text,
    )


def normalize_reference_period(value: str) -> str:
    match = re.search(
        r"제\s*(\d+)\s*기\s*[:：]\s*[’']?(\d{2,4})\s*\.\s*(\d{1,2})\s*\.?\s*[~∼-]\s*[’']?(\d{2,4})\s*\.\s*(\d{1,2})",
        value,
    )
    if not match:
        return re.sub(r"\s+", " ", value.strip("[] ")).strip()

    term, start_year, start_month, end_year, end_month = match.groups()
    return (
        f"제{int(term)}기: {normalize_year(start_year)}. {int(start_month)}. "
        f"~ {normalize_year(end_year)}. {int(end_month)}."
    )


def normalize_year(value: str) -> str:
    if len(value) == 2:
        return f"20{value}"
    return value


def normalize_base_date(value: str) -> str:
    match = re.search(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})", value)
    if not match:
        return re.sub(r"\s+", " ", value).strip()

    year, month, day = match.groups()
    return f"{year}. {int(month)}. {int(day)}."


def is_metadata_row(row: list[str]) -> bool:
    non_empty_cells = [cell.strip() for cell in row if cell.strip()]
    joined = " ".join(non_empty_cells)
    return is_metadata_text(joined, unique_cell_count=len(set(non_empty_cells)))


def is_metadata_text(text: str, *, unique_cell_count: int | None = None) -> bool:
    joined = re.sub(r"\s+", " ", text).strip()
    has_reference_period = reference_period_match(joined) is not None
    has_base_date = re.search(
        r"\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}\s*\.?\s*기준",
        joined,
    ) is not None
    limited_repetition = unique_cell_count is None or unique_cell_count <= 2
    if "단위" in joined and ("기준" in joined or "As of" in joined):
        return True
    if "단위" in joined and has_reference_period and limited_repetition:
        return True
    if (has_base_date or "As of" in joined) and limited_repetition:
        return True
    if has_reference_period and limited_repetition:
        return True
    return False


def is_note_continuation_text(text: str, existing_notes: list[str]) -> bool:
    return bool(existing_notes and re.match(r"^\s*[-–]\s*\S", text))


def is_embedded_source_row(row: list[str]) -> bool:
    non_empty_cells = [cell.strip() for cell in row if cell.strip()]
    if not non_empty_cells:
        return False
    joined = " ".join(non_empty_cells)
    return bool(
        re.search(r"(?:주무관|사무관|담당자)", joined)
        and re.search(r"\d{2,4}[-)]\d{3,4}-\d{4}", joined)
    )


def merge_footnote_markers(*values: str) -> str:
    markers: list[str] = []
    for value in values:
        for marker in value.split():
            if marker and marker not in markers:
                markers.append(marker)
    return " ".join(markers)


def compact_table_part(part: TablePart) -> TablePart:
    """Remove HWPX grid columns that contain no visible cell content.

    HWPX can represent a merged first column as several grid columns on one
    page, then use a single grid column on the next page.  Keeping those empty
    grid columns makes the two pages look like unrelated 14- and 7-column
    tables even though the rendered table has the same seven columns.
    """

    width = max(
        max((len(row) for row in part.matrix), default=0),
        max((len(row) for row in part.footnote_matrix), default=0),
    )
    used_columns = [
        col_index
        for col_index in range(width)
        if any(
            col_index < len(row) and row[col_index].strip()
            for row in part.matrix
        )
        or any(
            col_index < len(row) and row[col_index].strip()
            for row in part.footnote_matrix
        )
    ]
    if not used_columns or len(used_columns) == width:
        return part

    return TablePart(
        section_file=part.section_file,
        matrix=[
            [row[col_index] if col_index < len(row) else "" for col_index in used_columns]
            for row in part.matrix
        ],
        raw_text=part.raw_text,
        footnote_matrix=[
            [row[col_index] if col_index < len(row) else "" for col_index in used_columns]
            for row in part.footnote_matrix
        ],
    )


def part_content_rows(part: TablePart) -> list[list[str]]:
    compacted = compact_table_part(part)
    return [
        row
        for row in compacted.matrix
        if any(cell.strip() for cell in row)
        and not is_metadata_row(row)
        and not is_subtable_caption_row(row)
    ]


def is_subtable_caption_row(row: list[str]) -> bool:
    non_empty = [cell.strip() for cell in row if cell.strip()]
    return len(non_empty) == 1 and non_empty[0].startswith("▫")


def subtable_caption(part: TablePart) -> str:
    for row in part.matrix:
        if is_subtable_caption_row(row):
            value = next(cell for cell in row if cell.strip())
            return re.sub(r"\s+", "", value).lower()
        if any(cell.strip() for cell in row) and not is_metadata_row(row):
            break
    return ""


def split_table_part_at_subtable_captions(part: TablePart) -> list[TablePart]:
    """Split multiple rendered subtables stored inside a single HWPX table."""

    caption_indexes = [
        row_index
        for row_index, row in enumerate(part.matrix)
        if is_subtable_caption_row(row)
    ]
    if len(caption_indexes) <= 1:
        return [part]

    boundaries = [*caption_indexes, len(part.matrix)]
    split_parts: list[TablePart] = []
    for index in range(len(boundaries) - 1):
        start = boundaries[index]
        end = boundaries[index + 1]
        matrix = part.matrix[start:end]
        if not any(cell.strip() for row in matrix for cell in row):
            continue
        split_parts.append(
            TablePart(
                section_file=part.section_file,
                matrix=matrix,
                raw_text="\n".join(
                    cell.strip()
                    for row in matrix
                    for cell in row
                    if cell.strip()
                ),
                footnote_matrix=part.footnote_matrix[start:end],
            )
        )
    return split_parts or [part]


def header_signature(rows: list[list[str]]) -> tuple[tuple[str, ...], ...] | None:
    if not rows or looks_like_data_row(rows[0]):
        return None
    header_count = guess_header_count(rows)
    return tuple(
        tuple(re.sub(r"\s+", "", cell).lower() for cell in row)
        for row in rows[:header_count]
    )


def compatible_part_structure(
    left: tuple[int, tuple[tuple[str, ...], ...] | None],
    right: tuple[int, tuple[tuple[str, ...], ...] | None],
) -> bool:
    left_width, left_header = left
    right_width, right_header = right
    if left_width != right_width:
        return False
    if left_header is None or right_header is None:
        return True
    if left_header == right_header:
        return True
    shorter, longer = sorted((left_header, right_header), key=len)
    return bool(shorter) and longer[-len(shorter) :] == shorter


def rows_start_with_header(
    rows: list[list[str]],
    header: tuple[tuple[str, ...], ...] | None,
) -> bool:
    if not header or len(rows) < len(header):
        return False
    prefix = tuple(
        tuple(re.sub(r"\s+", "", cell).lower() for cell in row)
        for row in rows[: len(header)]
    )
    return prefix == header


def split_hwpx_table_by_part_structure(table: LogicalTable) -> list[LogicalTable]:
    """Split true subtables while retaining page continuations as one table."""

    expanded_parts = [
        split_part
        for part in table.parts
        for split_part in split_table_part_at_subtable_captions(part)
    ]
    compacted_parts = [compact_table_part(part) for part in expanded_parts]
    if len(compacted_parts) <= 1:
        table.parts = compacted_parts
        return [table]

    groups: list[
        tuple[
            tuple[int, tuple[tuple[str, ...], ...] | None],
            str,
            list[TablePart],
        ]
    ] = []
    for part in compacted_parts:
        rows = part_content_rows(part)
        width = max((len(row) for row in rows), default=0)
        structure = (width, header_signature(rows))
        caption = subtable_caption(part)
        prior_caption = groups[-1][1] if groups else ""
        starts_distinct_caption = bool(
            caption and prior_caption and caption != prior_caption
        )
        repeats_prior_header = bool(
            groups
            and width == groups[-1][0][0]
            and rows_start_with_header(rows, groups[-1][0][1])
        )
        if (
            groups
            and not starts_distinct_caption
            and (
                repeats_prior_header
                or compatible_part_structure(groups[-1][0], structure)
            )
        ):
            groups[-1][2].append(part)
        else:
            groups.append((structure, caption, [part]))

    if len(groups) <= 1:
        table.parts = compacted_parts
        return [table]

    return [
        LogicalTable(
            code=f"{table.code} 표{group_index}",
            title=table.title,
            title_en=table.title_en,
            section_title=table.section_title,
            section_title_en=table.section_title_en,
            section_file=table.section_file,
            table_order=table.table_order,
            parts=parts,
            notes=list(table.notes),
            sources=list(table.sources),
            metadata_context=table.metadata_context,
        )
        for group_index, (_, _, parts) in enumerate(groups, start=1)
    ]


def split_hwpx_tables_by_part_structure(
    tables: Iterable[LogicalTable],
) -> list[LogicalTable]:
    split_tables: list[LogicalTable] = []
    for table in tables:
        split_tables.extend(split_hwpx_table_by_part_structure(table))
    for table_order, table in enumerate(split_tables, start=1):
        table.table_order = table_order
    return split_tables


def normalize_matrix_with_footnotes(
    parts: Iterable[TablePart],
    *,
    footnote_markers: Iterable[str] = (),
) -> tuple[list[list[str]], list[list[str]]]:
    rows: list[list[str]] = []
    footnote_rows: list[list[str]] = []
    max_cols = 0
    seen_data_signatures: set[tuple[str, ...]] = set()
    data_started = False
    known_markers = set(footnote_markers)
    canonical_header: tuple[tuple[str, ...], ...] | None = None

    for part in (compact_table_part(item) for item in parts):
        content_rows = [
            (row_index, row)
            for row_index, row in enumerate(part.matrix)
            if any(cell.strip() for cell in row)
            and not is_metadata_row(row)
            and not is_subtable_caption_row(row)
            and not is_embedded_source_row(row)
        ]
        current_rows = [row for _, row in content_rows]
        current_header = header_signature(current_rows)
        repeated_header_count = 0
        if current_header is not None:
            if canonical_header is None:
                canonical_header = current_header
            elif rows_start_with_header(current_rows, canonical_header):
                repeated_header_count = len(canonical_header)
            elif current_header == canonical_header:
                repeated_header_count = len(current_header)
            elif (
                len(current_header) <= len(canonical_header)
                and canonical_header[-len(current_header) :] == current_header
            ):
                repeated_header_count = len(current_header)

        for content_index, (row_index, row) in enumerate(content_rows):
            if content_index < repeated_header_count:
                continue
            if not any(cell.strip() for cell in row):
                continue
            parsed_cells = [split_cell_text(cell, known_markers) for cell in row]
            cleaned_row = [text for text, _ in parsed_cells]
            footnote_row = [
                merge_footnote_markers(
                    (
                        part.footnote_matrix[row_index][col_index]
                        if row_index < len(part.footnote_matrix)
                        and col_index < len(part.footnote_matrix[row_index])
                        else ""
                    ),
                    marker,
                )
                for col_index, (_, marker) in enumerate(parsed_cells)
            ]
            row_signature = tuple(cleaned_row)
            if data_started and row_signature in seen_data_signatures:
                continue
            if any(numeric_value(cell) is not None for cell in cleaned_row[1:]):
                data_started = True
            if data_started:
                seen_data_signatures.add(row_signature)
            max_cols = max(max_cols, len(cleaned_row))
            rows.append(cleaned_row)
            footnote_rows.append(footnote_row)

    normalized_rows = [row + [""] * (max_cols - len(row)) for row in rows]
    normalized_footnote_rows = [row + [""] * (max_cols - len(row)) for row in footnote_rows]
    repair_region_split_rows(normalized_rows, normalized_footnote_rows)
    return normalized_rows, normalized_footnote_rows


def normalize_matrix(parts: Iterable[TablePart]) -> list[list[str]]:
    matrix, _ = normalize_matrix_with_footnotes(parts)
    return matrix


def numeric_value(text: str) -> float | None:
    return parse_numeric_value(text)


def looks_like_data_row(row: list[str]) -> bool:
    first_cell = row[0] if row else ""
    if looks_like_total_data_label(first_cell):
        return True
    if looks_like_header_label(first_cell):
        return False
    if re.fullmatch(r"\d{4}", re.sub(r"\s+", "", first_cell)):
        return True
    if any(numeric_value(cell) is not None for cell in row[1:]):
        return True
    return looks_like_text_data_row(row)


def looks_like_total_data_label(value: str) -> bool:
    cleaned = re.sub(r"\s+", " ", value).strip()
    return bool(
        re.match(r"^(?:합\s*계|총\s*계|소\s*계)(?:\s|$|[(:\[])", cleaned, re.IGNORECASE)
        or re.match(r"^계(?:\s+(?:total|sum)\b|\s*$|\s*[(:\[])", cleaned, re.IGNORECASE)
    )


def looks_like_text_data_row(row: list[str]) -> bool:
    non_empty_cells = [cell.strip() for cell in row if cell.strip()]
    if len(non_empty_cells) < 2:
        return False

    if any(re.search(r"(?:'\d{2}|’\d{2}|\d{4})[.\-/년]", re.sub(r"\s+", "", cell)) for cell in non_empty_cells):
        return True
    first_cell = non_empty_cells[0]
    if re.search(r"[A-Z][a-z]{2,}\.?\s+\d{1,2}", first_cell):
        return True

    body_like_cells = [
        cell
        for cell in non_empty_cells[1:]
        if len(re.sub(r"\s+", "", cell)) >= 20
        and re.search(r"[,，;:‧]", cell)
    ]
    return bool(body_like_cells)


def looks_like_header_label(value: str) -> bool:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    for line in lines:
        compact_line = re.sub(r"\s+", "", line).lower()
        if compact_line in KOREAN_HEADER_LABELS or compact_line in ENGLISH_HEADER_LABELS:
            return True

    compact = re.sub(r"\s+", "", value).lower()
    return any(f"{ko}{english}" in compact for ko, english in HEADER_LABEL_PAIRS)


def guess_header_count(matrix: list[list[str]]) -> int:
    for index, row in enumerate(matrix[:8]):
        if looks_like_data_row(row):
            return max(index, 1)
    return 1 if matrix else 0


def domain_from_code(code: str) -> str:
    chapter = code.split("-", 1)[0]
    return DOMAIN_BY_CHAPTER.get(chapter, "통계")


def import_hwpx(
    source_path: Path,
    *,
    db_path: Path = DB_PATH,
    year: int = 2025,
    title: str | None = None,
    run_validation: bool = True,
) -> dict[str, int | str]:
    source_path = source_path.expanduser().resolve()
    report_title = title or f"{year} 행정안전통계연보"
    from app.ingest.parser_registry import parse_report

    report = parse_report(
        source_path,
        source_type="hwpx",
        year=year,
        title=report_title,
    )
    result = ReportImportRepository(db_path).replace_parsed_report(
        report,
    )

    validation_issues = 0
    if run_validation:
        from app.validation.run_validations import run_validations

        validation_result = run_validations(db_path, report_id=result.report_id)
        validation_issues = int(validation_result["issues"])

    return {
        "db_path": str(db_path),
        "source_file": str(source_path),
        "report_id": result.report_id,
        "tables": result.table_count,
        "cells": result.cell_count,
        "validation_issues": validation_issues,
    }


def prepare_hwpx_import_tables(
    parsed_tables: list[LogicalTable],
    *,
    report_year: int | None = None,
) -> list[ImportedTable]:
    imported_tables: list[ImportedTable] = []
    prepared_tables = split_hwpx_tables_by_part_structure(parsed_tables)
    inherited_units: dict[str, set[str]] = {}
    inherited_base_dates: dict[tuple[str, str], str] = {}
    inherited_sources: dict[str, set[str]] = {}
    for table in annotate_adjacent_duplicate_tables(prepared_tables):
        matrix, footnote_matrix = normalize_matrix_with_footnotes(
            table.parts,
            footnote_markers=footnote_markers_from_texts(table.notes),
        )
        if not matrix or max((len(row) for row in matrix), default=0) < 2:
            continue
        stored_matrix = [
            [restore_hyphenated_line_breaks(value) for value in row]
            for row in matrix
        ]
        raw_text = " ".join(part.raw_text for part in table.parts)
        metadata_text = " ".join(value for value in (table.metadata_context, raw_text) if value)
        unit, base_date = extract_unit_and_base_date(raw_text)
        shared_unit, shared_base_date = extract_unit_and_base_date(metadata_text)
        unit = unit or shared_unit
        base_date = base_date or shared_base_date
        parent_code = metadata_inheritance_code(table.code)
        if not unit and parent_code:
            parent_units = inherited_units.get(parent_code, set())
            if len(parent_units) == 1:
                unit = next(iter(parent_units))
        unit_key = metadata_unit_key(unit)
        if not base_date and parent_code and unit_key:
            base_date = inherited_base_dates.get((parent_code, unit_key), "")
        if not base_date and unit:
            base_date = default_base_date_for_report_year(report_year)
        source = "\n".join(normalize_table_sources(table.code, table.sources))
        if not source and parent_code:
            parent_sources = inherited_sources.get(parent_code, set())
            if len(parent_sources) == 1:
                source = next(iter(parent_sources))
        if unit and parent_code:
            inherited_units.setdefault(parent_code, set()).add(unit)
        if base_date and parent_code and unit_key:
            inherited_base_dates[(parent_code, unit_key)] = base_date
        if source and parent_code:
            inherited_sources.setdefault(parent_code, set()).add(source)
        imported_tables.append(
            ImportedTable(
                code=table.code,
                title=table.title,
                title_en=table.title_en,
                section_title=table.section_title or table.title,
                section_title_en=table.section_title_en or table.title_en,
                domain=domain_from_code(table.code),
                unit=unit,
                base_date=base_date,
                section_file=table.section_file,
                table_order=table.table_order,
                note="\n".join(table.notes),
                source=source,
                raw_context=raw_text,
                matrix=stored_matrix,
                header_count=guess_header_count(stored_matrix),
                footnote_matrix=footnote_matrix,
            )
        )
    return normalize_single_appendix_part_codes(imported_tables)


def normalize_single_appendix_part_codes(
    imported_tables: list[ImportedTable],
) -> list[ImportedTable]:
    base_counts: dict[str, int] = {}
    appendix_part_re = re.compile(r"^(부록\s+\d+(?:-\d+)?)\s+표\d+$")
    for table in imported_tables:
        match = appendix_part_re.match(table.code)
        if match:
            base_counts[match.group(1)] = base_counts.get(match.group(1), 0) + 1

    existing_codes = {table.code for table in imported_tables}
    normalized_tables: list[ImportedTable] = []
    for table in imported_tables:
        match = appendix_part_re.match(table.code)
        if match and base_counts.get(match.group(1)) == 1 and match.group(1) not in existing_codes:
            normalized_tables.append(replace(table, code=match.group(1)))
        else:
            normalized_tables.append(table)
    return normalized_tables


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import an HWPX annual statistics report into SQLite.")
    parser.add_argument("source", type=Path, help="Path to the HWPX file")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="SQLite database path")
    parser.add_argument("--year", type=int, default=2025, help="Report year")
    parser.add_argument("--title", default=None, help="Report title")
    parser.add_argument("--skip-validation", action="store_true", help="Skip rule-based validation")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = import_hwpx(
        args.source,
        db_path=args.db,
        year=args.year,
        title=args.title,
        run_validation=not args.skip_validation,
    )
    print(
        "Imported {tables} tables and {cells} cells into {db_path}; validation issues: {validation_issues}".format(**result)
    )


if __name__ == "__main__":
    main()
