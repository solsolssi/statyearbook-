from __future__ import annotations

import re
from typing import Any

from app.validation.models import ValidationTable, normalize_text
from app.validation.rules import combined_row_label


YEAR_LABEL_RE = re.compile(r"^((?:19|20)\d{2})(?:년|year)?$")


def resolve_row_scope(table: ValidationTable, spec: dict[str, Any]) -> list[int]:
    """Resolve a profile rule's row scope against the current table.

    Fixed coordinates remain available for one-off totals.  Rolling tables use
    a semantic scope so a newly supplied year is checked as soon as its values
    exist, without changing the profile or asking an LLM to rediscover the
    same arithmetic.
    """

    scope = str(spec.get("row_scope") or "fixed")
    fixed_rows = [int(value) for value in spec.get("row_indices", [])]
    data_rows = list(table.data_rows())
    if scope == "all_data_rows":
        return [row_index for row_index, _ in data_rows]
    if scope not in {"year_rows", "year_first_occurrence", "year_range"}:
        return fixed_rows

    year_min = int(spec["year_min"]) if spec.get("year_min") is not None else None
    year_max = int(spec["year_max"]) if spec.get("year_max") is not None else None
    selected: list[tuple[int, int]] = []
    for row_index, row in data_rows:
        year = row_year(table, row)
        if year is None:
            continue
        if year_min is not None and year < year_min:
            continue
        if year_max is not None and year > year_max:
            continue
        selected.append((row_index, year))

    if scope == "year_first_occurrence":
        seen_years: set[int] = set()
        return [
            row_index
            for row_index, year in selected
            if not (year in seen_years or seen_years.add(year))
        ]
    return [row_index for row_index, _ in selected]


def row_year(table: ValidationTable, row: list) -> int | None:
    label = normalize_text(combined_row_label(table, row) or table.row_label(row))
    matched = YEAR_LABEL_RE.fullmatch(label)
    if matched is None:
        return None
    return int(matched.group(1))
