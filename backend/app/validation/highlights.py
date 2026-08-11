from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from app.db.connection import DatabaseRow
from app.domain.enums import HighlightRole, HighlightScope
from app.domain.validation import HighlightTarget
from app.models.report import ValidationHighlightCell, ValidationHighlightRow
from app.validation.catalog import CALCULATION_RULE_TYPES, GROWTH_RATE_RULE_TYPES


@dataclass(frozen=True)
class ResolvedHighlights:
    scope: str
    cells: list[ValidationHighlightCell]
    rows: list[ValidationHighlightRow]
    focus_cell: ValidationHighlightCell | None


@dataclass(frozen=True)
class HighlightPlan:
    """Semantic highlight roles before they are adapted to the current API."""

    scope: HighlightScope | str
    targets: tuple[HighlightTarget, ...] = ()
    operands: tuple[HighlightTarget, ...] = ()
    related: tuple[HighlightTarget, ...] = ()
    headers: tuple[HighlightTarget, ...] = ()

    @property
    def all_targets(self) -> tuple[HighlightTarget, ...]:
        return self.targets + self.operands + self.related + self.headers


class HighlightResolver:
    """Single source of truth for rule-result, API, and export highlights."""

    def plan(
        self,
        row: DatabaseRow,
        *,
        spec: dict[str, Any] | None,
        header_count: int,
        matrix: list[list[Any]] | None,
    ) -> HighlightPlan:
        cells = _profile_highlight_cells(row, spec, matrix)
        rule_type = str((spec or {}).get("type") or "")
        calculation_rule = (
            rule_type in CALCULATION_RULE_TYPES
            or rule_type in GROWTH_RATE_RULE_TYPES
            or rule_type
            in {
                "row_year_over_year_change_amount",
                "year_rows_change_amount",
                "cross_split_operand_row",
                "weighted_average",
            }
        )
        targets: list[HighlightTarget] = []
        operands: list[HighlightTarget] = []
        related: list[HighlightTarget] = []
        headers: list[HighlightTarget] = []
        for cell in cells:
            if cell.role == HighlightRole.TARGET:
                targets.append(
                    HighlightTarget(
                        row_index=cell.row_index,
                        col_index=cell.col_index,
                        role=HighlightRole.TARGET,
                        scope=HighlightScope.CELL,
                    )
                )
                continue

            target = HighlightTarget(
                row_index=cell.row_index,
                col_index=cell.col_index,
                role=HighlightRole.RELATED,
                scope=HighlightScope.CELL,
            )
            if calculation_rule:
                operands.append(
                    HighlightTarget(
                        row_index=target.row_index,
                        col_index=target.col_index,
                        role=HighlightRole.OPERAND,
                        scope=target.scope,
                    )
                )
            elif cell.row_index < header_count:
                headers.append(
                    HighlightTarget(
                        row_index=target.row_index,
                        col_index=target.col_index,
                        role=HighlightRole.HEADER,
                        scope=HighlightScope.HEADER,
                    )
                )
            else:
                related.append(target)

        return HighlightPlan(
            scope=highlight_scope_for(row, spec, header_count),
            targets=tuple(targets),
            operands=tuple(operands),
            related=tuple(related),
            headers=tuple(headers),
        )

    def resolve(
        self,
        row: DatabaseRow,
        *,
        spec: dict[str, Any] | None,
        header_count: int,
        matrix: list[list[Any]] | None,
    ) -> ResolvedHighlights:
        plan = self.plan(
            row,
            spec=spec,
            header_count=header_count,
            matrix=matrix,
        )
        cells = self.presentation_cells(plan)
        focus = next((cell for cell in cells if cell.role == "target"), None)
        return ResolvedHighlights(
            scope=str(plan.scope),
            cells=cells,
            rows=highlight_rows_for(row, spec),
            focus_cell=focus or next(iter(cells), None),
        )

    @staticmethod
    def presentation_cells(plan: HighlightPlan) -> list[ValidationHighlightCell]:
        """Keep the public target/related contract while retaining richer roles."""

        cells: list[ValidationHighlightCell | None] = []
        for target in plan.all_targets:
            public_role = (
                HighlightRole.TARGET.value
                if target.role == HighlightRole.TARGET
                else HighlightRole.RELATED.value
            )
            cells.append(highlight_cell(target.row_index, target.col_index, public_role))
        return unique_highlight_cells(cells)


DEFAULT_HIGHLIGHT_RESOLVER = HighlightResolver()


def resolve_highlights(
    row: DatabaseRow,
    *,
    spec: dict[str, Any] | None,
    header_count: int,
    matrix: list[list[Any]] | None,
) -> ResolvedHighlights:
    return DEFAULT_HIGHLIGHT_RESOLVER.resolve(
        row,
        spec=spec,
        header_count=header_count,
        matrix=matrix,
    )


def highlight_targets_for(
    row: DatabaseRow,
    *,
    spec: dict[str, Any] | None,
    header_count: int,
    matrix: list[list[Any]] | None = None,
) -> tuple[HighlightTarget, ...]:
    return DEFAULT_HIGHLIGHT_RESOLVER.plan(
        row,
        spec=spec,
        header_count=header_count,
        matrix=matrix,
    ).all_targets


def int_or_none(value: Any) -> int | None:
    return int(value) if value is not None else None


def highlight_cell(
    row_index: int | None,
    col_index: int | None,
    role: str,
) -> ValidationHighlightCell | None:
    if row_index is None or col_index is None or row_index < 0 or col_index < 0:
        return None
    return ValidationHighlightCell(row_index=row_index, col_index=col_index, role=role)


def highlight_row(row_index: int | None, role: str) -> ValidationHighlightRow | None:
    if row_index is None or row_index < 0:
        return None
    return ValidationHighlightRow(row_index=row_index, role=role)


def unique_highlight_cells(
    cells: list[ValidationHighlightCell | None],
) -> list[ValidationHighlightCell]:
    merged: dict[tuple[int, int], ValidationHighlightCell] = {}
    for cell in cells:
        if cell is None:
            continue
        key = (cell.row_index, cell.col_index)
        current = merged.get(key)
        if current is None or cell.role == "target":
            merged[key] = cell
    return list(merged.values())


def spec_columns(spec: dict[str, Any] | None, key: str) -> list[int]:
    if not spec:
        return []
    return [int(value) for value in spec.get(key, []) if value is not None]


def spec_rows(spec: dict[str, Any] | None, key: str) -> list[int]:
    if not spec:
        return []
    return [int(value) for value in spec.get(key, []) if value is not None]


def relation_cell_for_view(
    descriptor: Any,
    matrix: list[list[Any]] | None,
) -> tuple[int, int] | None:
    """Resolve a profile relation cell for exact table-cell highlighting."""

    if not isinstance(descriptor, dict):
        return None
    column = int(descriptor.get("column", -1))
    if column < 0:
        return None

    if descriptor.get("row") is not None:
        row = int(descriptor.get("row", -1))
        return (row, column) if row >= 0 else None
    if not matrix:
        return None

    selector = str(descriptor.get("row_selector") or "")
    if selector == "latest_year":
        candidates: list[tuple[int, int]] = []
        for row_index, cells in enumerate(matrix):
            label = matrix_row_label(cells)
            match = re.fullmatch(r"(?:19|20)(\d{2})", label)
            if match:
                candidates.append((int(match.group(0)), row_index))
        if candidates:
            return max(candidates)[1], column

    if selector == "cumulative_total":
        for row_index, cells in enumerate(matrix):
            label = normalize_lookup_text(matrix_row_label(cells))
            if "누적계" in label or "cumulativetotal" in label:
                return row_index, column

    return None


def matrix_row_label(cells: list[Any]) -> str:
    if not cells or cells[0] is None:
        return ""
    return clean_table_cell_text(cells[0])


def clean_table_cell_text(cell: Any) -> str:
    if isinstance(cell, str):
        value = cell
    elif hasattr(cell, "keys") and "text_value" in cell.keys():
        value = cell["text_value"]
    elif hasattr(cell, "text_value"):
        value = cell.text_value
    elif isinstance(cell, dict):
        value = cell.get("text_value", "")
    else:
        value = str(cell or "")
    return re.sub(r"\s+", " ", str(value or "")).strip()


def column_sum_operand_rows_for_view(
    spec: dict[str, Any],
    *,
    target_row: int,
    matrix: list[list[Any]] | None,
) -> list[int]:
    """Resolve dynamic operands so persisted checks highlight their source cells."""

    if spec.get("operand_row_selector") == "following_data_rows" and matrix:
        return [
            row_index
            for row_index in range(target_row + 1, len(matrix))
            if any(clean_table_cell_text(cell) for cell in matrix[row_index])
        ]
    return spec_rows(spec, "operand_rows")


def normalize_lookup_text(value: str) -> str:
    return re.sub(r"[\s·,._\-()/%]+", "", value).lower()


def formula_previous_column(
    spec: dict[str, Any] | None,
    current_col: int | None,
) -> int | None:
    if spec is None or current_col is None:
        return None
    ordered_columns = sorted(spec_columns(spec, "columns"))
    previous_columns = [col_index for col_index in ordered_columns if col_index < current_col]
    return previous_columns[-1] if previous_columns else None


def _profile_highlight_cells(
    row: DatabaseRow,
    spec: dict[str, Any] | None,
    matrix: list[list[Any]] | None = None,
) -> list[ValidationHighlightCell]:
    row_index = int_or_none(row["row_index"])
    col_index = int_or_none(row["col_index"])
    if spec is None:
        return fallback_highlight_cells(row)

    rule_type = str(spec.get("type") or "")
    cells: list[ValidationHighlightCell | None] = []

    if rule_type in {"row_sum", "cross_table_row_sum"}:
        target_col = int(spec.get("target_column", col_index if col_index is not None else -1))
        cells.append(highlight_cell(row_index, target_col, "target"))
        cells.extend(
            highlight_cell(row_index, col, "related")
            for col in spec_columns(spec, "operand_columns")
        )
    elif rule_type == "cross_table_weighted_average":
        target_row = int(spec.get("target_row", row_index if row_index is not None else -1))
        target_col = int(spec.get("target_column", col_index if col_index is not None else -1))
        value_col = int(spec.get("value_column", target_col))
        cells.append(highlight_cell(target_row, target_col, "target"))
        for pair in spec.get("row_pairs", []):
            if isinstance(pair, dict):
                cells.append(highlight_cell(int(pair.get("value_row", -1)), value_col, "related"))
    elif rule_type == "cross_table_cell_match":
        cells.append(highlight_cell(row_index, col_index, "target"))
    elif rule_type == "cell_sum":
        target_row = int(spec.get("target_row", row_index if row_index is not None else -1))
        target_col = int(spec.get("target_column", col_index if col_index is not None else -1))
        cells.append(highlight_cell(target_row, target_col, "target"))
        for operand in spec.get("operand_cells", []):
            if isinstance(operand, dict):
                cells.append(
                    highlight_cell(
                        int(operand.get("row", -1)),
                        int(operand.get("column", -1)),
                        "related",
                    )
                )
    elif rule_type == "cell_relation_sum":
        for comparison in spec.get("comparisons", []):
            if not isinstance(comparison, dict):
                continue
            target = relation_cell_for_view(comparison.get("target"), matrix)
            if target is None:
                continue
            target_row, target_col = target
            if target_row != row_index or target_col != col_index:
                continue
            cells.append(highlight_cell(target_row, target_col, "target"))
            for operand in comparison.get("operand_cells", []):
                resolved_operand = relation_cell_for_view(operand, matrix)
                if resolved_operand is not None:
                    cells.append(highlight_cell(*resolved_operand, "related"))
            break
    elif rule_type == "row_arithmetic":
        target_col = int(spec.get("target_column", col_index if col_index is not None else -1))
        cells.append(highlight_cell(row_index, target_col, "target"))
        term_columns = [
            int(term.get("column", -1))
            for term in spec.get("terms", [])
            if isinstance(term, dict) and term.get("column") is not None
        ]
        cells.extend(highlight_cell(row_index, col, "related") for col in term_columns)
    elif rule_type == "row_ratio":
        target_col = int(spec.get("target_column", col_index if col_index is not None else -1))
        numerator_col = int(spec.get("numerator_column", -1))
        denominator_columns = spec_columns(spec, "denominator_columns")
        denominator_col = int(spec.get("denominator_column", -1))
        if not denominator_columns and denominator_col >= 0:
            denominator_columns = [denominator_col]
        cells.extend(
            [
                highlight_cell(row_index, target_col, "target"),
                highlight_cell(row_index, numerator_col, "related"),
            ]
        )
        cells.extend(
            highlight_cell(row_index, denominator_col, "related")
            for denominator_col in denominator_columns
        )
    elif rule_type == "column_share_ratio":
        target_col = int(spec.get("target_column", col_index if col_index is not None else -1))
        numerator_col = int(spec.get("numerator_column", -1))
        denominator_row = int(spec.get("denominator_row", -1))
        denominator_col = int(spec.get("denominator_column", numerator_col))
        cells.extend(
            [
                highlight_cell(row_index, target_col, "target"),
                highlight_cell(row_index, numerator_col, "related"),
                highlight_cell(denominator_row, denominator_col, "related"),
            ]
        )
    elif rule_type == "row_growth_rate":
        target_col = int(spec.get("target_column", col_index if col_index is not None else -1))
        current_col = int(spec.get("current_column", -1))
        previous_col = int(spec.get("previous_column", -1))
        cells.extend(
            [
                highlight_cell(row_index, target_col, "target"),
                highlight_cell(row_index, current_col, "related"),
                highlight_cell(row_index, previous_col, "related"),
            ]
        )
    elif rule_type in {"column_sum", "region_total"}:
        target_row = int(spec.get("target_row", row_index if row_index is not None else -1))
        rule_columns = spec_columns(spec, "columns")
        current_col = col_index if col_index is not None else (rule_columns[0] if rule_columns else -1)
        cells.append(highlight_cell(target_row, current_col, "target"))
        for operand_row in column_sum_operand_rows_for_view(
            spec,
            target_row=target_row,
            matrix=matrix,
        ):
            cells.append(highlight_cell(operand_row, current_col, "related"))
    elif rule_type == "row_ratio_by_rows":
        target_row = int(spec.get("target_row", row_index if row_index is not None else -1))
        numerator_row = int(spec.get("numerator_row", -1))
        cells.extend(
            [
                highlight_cell(target_row, col_index, "target"),
                highlight_cell(numerator_row, col_index, "related"),
            ]
        )
        denominator_rows = spec_rows(spec, "denominator_rows")
        if not denominator_rows:
            denominator_rows = [int(spec.get("denominator_row", -1))]
        cells.extend(
            highlight_cell(denominator_row, col_index, "related")
            for denominator_row in denominator_rows
        )
    elif rule_type == "weighted_average":
        target_row = int(spec.get("target_row", row_index if row_index is not None else -1))
        target_col = int(spec.get("target_column", col_index if col_index is not None else -1))
        value_col = int(spec.get("value_column", -1))
        weight_col = int(spec.get("weight_column", -1))
        cells.append(highlight_cell(target_row, target_col, "target"))
        for operand_row in spec_rows(spec, "operand_rows"):
            cells.append(highlight_cell(operand_row, value_col, "related"))
            cells.append(highlight_cell(operand_row, weight_col, "related"))
    elif rule_type == "row_year_over_year_rate":
        target_row = row_index if row_index is not None else int(spec.get("target_row", -1))
        source_row = next(
            (
                int(pair.get("source_row", -1))
                for pair in spec.get("row_pairs", [])
                if isinstance(pair, dict) and int(pair.get("target_row", -1)) == target_row
            ),
            int(spec.get("source_row", -1)),
        )
        previous_col = formula_previous_column(spec, col_index)
        cells.extend(
            [
                highlight_cell(target_row, col_index, "target"),
                highlight_cell(source_row, col_index, "related"),
                highlight_cell(source_row, previous_col, "related"),
            ]
        )
    elif rule_type == "row_year_over_year_change_amount":
        target_row = int(spec.get("target_row", row_index if row_index is not None else -1))
        source_row = int(spec.get("source_row", -1))
        previous_col = formula_previous_column(spec, col_index)
        cells.extend(
            [
                highlight_cell(target_row, col_index, "target"),
                highlight_cell(source_row, col_index, "related"),
                highlight_cell(source_row, previous_col, "related"),
            ]
        )
    elif rule_type == "year_rows_change_rate":
        value_col = int(spec.get("value_column", -1))
        change_col = spec.get("change_column")
        change_col_value = int(change_col) if change_col is not None else None
        rate_col = int(spec.get("rate_column", -1))
        row_indices = sorted(spec_rows(spec, "row_indices"))
        previous_rows = [
            candidate
            for candidate in row_indices
            if row_index is not None and candidate < row_index
        ]
        previous_row = previous_rows[-1] if previous_rows else None
        if change_col_value is not None and col_index == change_col_value:
            cells.append(highlight_cell(row_index, change_col_value, "target"))
        elif col_index == rate_col:
            cells.append(highlight_cell(row_index, rate_col, "target"))
        else:
            cells.append(highlight_cell(row_index, col_index, "target"))
        cells.extend(
            [
                highlight_cell(row_index, value_col, "related"),
                highlight_cell(previous_row, value_col, "related"),
            ]
        )
    elif rule_type == "year_rows_change_amount":
        value_col = int(spec.get("value_column", -1))
        change_col = int(spec.get("change_column", col_index if col_index is not None else -1))
        row_indices = sorted(spec_rows(spec, "row_indices"))
        previous_rows = [
            candidate
            for candidate in row_indices
            if row_index is not None and candidate < row_index
        ]
        previous_row = previous_rows[-1] if previous_rows else None
        cells.extend(
            [
                highlight_cell(row_index, change_col, "target"),
                highlight_cell(row_index, value_col, "related"),
                highlight_cell(previous_row, value_col, "related"),
            ]
        )
    elif rule_type == "cross_split_operand_row":
        cells.extend(
            highlight_cell(row_index, col, "related")
            for col in spec_columns(spec, "operand_columns")
        )
    else:
        cells.append(highlight_cell(row_index, col_index, "target"))

    return unique_highlight_cells(cells)


def highlight_cells_for(
    row: DatabaseRow,
    spec: dict[str, Any] | None,
    matrix: list[list[Any]] | None = None,
) -> list[ValidationHighlightCell]:
    """Compatibility API shared by the web view and spreadsheet exports."""

    return DEFAULT_HIGHLIGHT_RESOLVER.resolve(
        row,
        spec=spec,
        header_count=0,
        matrix=matrix,
    ).cells


def highlight_rows_for(
    row: DatabaseRow,
    spec: dict[str, Any] | None,
) -> list[ValidationHighlightRow]:
    if spec is None:
        return fallback_highlight_rows(row)
    # Profile-backed checks use exact cells. Row highlights remain only as a
    # fallback for legacy issue records that have no column coordinate.
    return []


def highlight_scope_for(
    row: DatabaseRow,
    spec: dict[str, Any] | None,
    header_count: int,
) -> str:
    row_index = int_or_none(row["row_index"])
    if spec is None:
        return fallback_highlight_scope(row, header_count)

    rule_type = str(spec.get("type") or "")
    if rule_type in {"unit_required", "metadata_required"}:
        return "metadata"
    if row_index is not None and row_index < header_count:
        return "header"
    if rule_type in {
        "row_sum",
        "cell_sum",
        "cell_relation_sum",
        "row_arithmetic",
        "row_ratio",
        "column_share_ratio",
        "row_growth_rate",
        "row_year_over_year_change_amount",
        "year_rows_change_amount",
        "cross_split_operand_row",
        "cross_table_row_sum",
    }:
        return "row"
    if rule_type in {
        "column_sum",
        "region_total",
        "row_ratio_by_rows",
        "cross_table_weighted_average",
        "weighted_average",
    }:
        return "column"
    if rule_type in {"spelling_static", "translation_static"}:
        return "header" if row_index is not None and row_index < header_count else "cell"
    return "cell" if row_index is not None and row["col_index"] is not None else "none"


def fallback_highlight_cells(row: DatabaseRow) -> list[ValidationHighlightCell]:
    cell = highlight_cell(
        int_or_none(row["row_index"]),
        int_or_none(row["col_index"]),
        "target",
    )
    return [cell] if cell else []


def fallback_highlight_rows(row: DatabaseRow) -> list[ValidationHighlightRow]:
    if int_or_none(row["col_index"]) is not None:
        return []
    row_highlight = highlight_row(int_or_none(row["row_index"]), "target")
    return [row_highlight] if row_highlight else []


def fallback_highlight_scope(row: DatabaseRow, header_count: int) -> str:
    row_index = int_or_none(row["row_index"])
    col_index = int_or_none(row["col_index"])
    if row_index is None or col_index is None:
        return "none"
    if row_index < header_count:
        return "header"
    return "cell"
