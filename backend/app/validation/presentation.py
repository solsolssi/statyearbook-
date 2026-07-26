from __future__ import annotations

from typing import Any

from app.db.connection import DatabaseRow
from app.models.report import ValidationIssue
from app.validation.highlights import ResolvedHighlights, resolve_highlights


DISPLAY_CHECK_TYPE_MAP = {
    "증감액 검수": "합계 검수",
    "증감률 검수": "비율 검수",
    "평균 검수": "비율 검수",
}


def display_check_type(check_type: str) -> str:
    return DISPLAY_CHECK_TYPE_MAP.get(check_type, check_type)


def validation_display_group_key(row: DatabaseRow, check_type: str) -> str:
    """Return the canonical UI grouping key for one persisted validation result."""

    display_type = display_check_type(check_type)
    status = str(row["status"] or "")
    formula = str(row["formula"] or "").strip()
    rule_id = str(row["rule_id"] or "")
    location = str(row["location"] or "")
    row_index = row["row_index"]
    col_index = row["col_index"]
    current_value = str(row["current_value"] or "")
    expected_value = str(row["expected_value"] or "")
    detail = str(row["detail"] or "")

    if display_type in {"합계 검수", "비율 검수"} and (formula or rule_id):
        return f"repeated::{display_type}::{formula or rule_id}::{status}"

    exact_cell_key = "::".join(
        [
            location,
            "" if row_index is None else str(row_index),
            "" if col_index is None else str(col_index),
            current_value,
        ]
    )
    if display_type == "파란색 표기 확인":
        return f"blue-source::{status}::{exact_cell_key}"

    if display_type in {"오탈자 검수", "번역 검수"}:
        if status == "정상":
            return f"linguistic-pass::{display_type}"
        return "::".join(
            [
                "linguistic-problem",
                display_type,
                status,
                exact_cell_key,
                expected_value,
            ]
        )

    return "::".join(
        [
            "single-or-exact",
            rule_id or str(row["id"]),
            display_type,
            formula,
            detail,
            status,
        ]
    )


def validation_issue_from_row(
    row: DatabaseRow,
    *,
    issue_id: str,
    check_type: str,
    header_count: int,
    matrix: list[list[Any]] | None,
    spec: dict[str, Any] | None,
    include_highlights: bool = True,
) -> ValidationIssue:
    highlights = (
        resolve_highlights(row, spec=spec, header_count=header_count, matrix=matrix)
        if include_highlights
        else ResolvedHighlights(scope="none", cells=[], rows=[], focus_cell=None)
    )
    return ValidationIssue(
        id=issue_id,
        rule_id=row["rule_id"],
        type=display_check_type(check_type),
        location=row["location"],
        row_index=row["row_index"],
        col_index=row["col_index"],
        current_value=row["current_value"],
        expected_value=row["expected_value"],
        difference=row["difference"],
        status=row["status"],
        severity=row["severity"],
        detail=row["detail"],
        formula=row["formula"],
        display_group_key=validation_display_group_key(row, check_type),
        highlight_scope=highlights.scope,
        highlight_cells=highlights.cells,
        highlight_rows=highlights.rows,
        focus_cell=highlights.focus_cell,
    )
