from __future__ import annotations

import re


ROW_ORIENTED_DESCRIPTOR_HINTS = (
    "사유",
    "횟수",
    "지역",
    "장소",
    "일자",
    "기간",
    "내용",
    "대상",
    "reason",
    "number of",
    "area",
    "place",
    "date",
    "period",
    "description",
    "target",
)


def wide_row_oriented_text_table_header_count(matrix: list[list[str]]) -> int | None:
    """Detect wide text tables whose attributes run down rows, not headers."""

    if len(matrix) < 3:
        return None
    width = max((len(row) for row in matrix), default=0)
    if width < 5:
        return None

    first_cell = matrix[0][0].strip() if matrix and matrix[0] else ""
    normalized_first = normalize_text(first_cell)
    if "구분" not in normalized_first or "classification" not in normalized_first:
        return None

    descriptor_rows = 0
    dense_descriptor_rows = 0
    for row in matrix[1:5]:
        first = row[0].strip() if row else ""
        if not first:
            continue
        if normalize_text(first) == normalized_first:
            # Multi-row column headers often repeat the diagonal
            # ``구분/Classification/...`` cell down the first column.  Those
            # rows are still headers, not row-oriented body descriptors.
            return None
        if not descriptor_label_looks_row_oriented(first):
            continue
        descriptor_rows += 1
        non_empty_tail = [
            cell.strip()
            for cell in row[1:]
            if cell.strip()
        ]
        if len(non_empty_tail) >= max(3, width // 2):
            dense_descriptor_rows += 1

    if descriptor_rows >= 2 and dense_descriptor_rows >= 1:
        return 1
    return None


def descriptor_label_looks_row_oriented(value: str) -> bool:
    normalized = normalize_text(value)
    return any(hint in normalized for hint in ROW_ORIENTED_DESCRIPTOR_HINTS)


def normalize_text(value: str) -> str:
    return re.sub(r"[\s·･.,/&()]+", "", value).lower()
