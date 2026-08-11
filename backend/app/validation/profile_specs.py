from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.validation.catalog import SUPPORTED_PROFILE_SPEC_TYPES
from app.validation.models import ValidationTable
from app.validation.rules import column_count


PROFILE_DOCUMENT_VERSION = "validation-profile-v4"
PROFILE_SPEC_VERSION = 1
LEGACY_NON_EXECUTABLE_SPEC_TYPES = frozenset(
    {
        "row_label_required",
        "numeric_format",
        "year_sequence",
        "spelling_static",
        "translation_static",
    }
)


class ProfileCheckSpec(BaseModel):
    """Typed persistence contract for one executable validation check."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    label: str = ""
    category: str = "table"
    check_group: str = ""
    check_type: str = ""
    failure_status: str = "확인 필요"
    severity: str = "warning"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    execute: bool = True
    spec_version: int = PROFILE_SPEC_VERSION


class MetadataRequiredSpec(ProfileCheckSpec):
    type: Literal["metadata_required", "unit_required"]
    fields: list[str] = Field(default_factory=list)
    expected_unit: str = ""


class RowSumSpec(ProfileCheckSpec):
    type: Literal["row_sum"]
    target_column: int = Field(ge=0)
    operand_columns: list[int] = Field(min_length=1)
    row_indices: list[int] = Field(default_factory=list)
    row_scope: Literal["fixed", "all_data_rows", "year_rows", "year_first_occurrence", "year_range"] = "fixed"
    year_min: int | None = None
    year_max: int | None = None


class ColumnSumSpec(ProfileCheckSpec):
    type: Literal["column_sum", "region_total"]
    target_row: int | None = Field(default=None, ge=0)
    target_row_selector: Literal["first_total_row"] | None = None
    operand_rows: list[int] = Field(default_factory=list)
    operand_row_selector: Literal["following_data_rows"] | None = None
    columns: list[int] = Field(min_length=1)
    report_missing_target: bool = False

    @model_validator(mode="after")
    def require_target_and_operands(self) -> ColumnSumSpec:
        if self.target_row is None and self.target_row_selector is None:
            raise ValueError("target_row 또는 target_row_selector가 필요합니다.")
        if not self.operand_rows and self.operand_row_selector is None:
            raise ValueError("operand_rows 또는 operand_row_selector가 필요합니다.")
        return self


class CellCoordinate(BaseModel):
    model_config = ConfigDict(extra="allow")

    row: int | None = Field(default=None, ge=0)
    row_selector: str | None = None
    column: int = Field(ge=0)

    @model_validator(mode="after")
    def require_row_or_selector(self) -> CellCoordinate:
        if self.row is None and not self.row_selector:
            raise ValueError("row 또는 row_selector가 필요합니다.")
        return self


class CellSumSpec(ProfileCheckSpec):
    type: Literal["cell_sum"]
    target_row: int = Field(ge=0)
    target_column: int = Field(ge=0)
    operand_cells: list[CellCoordinate] = Field(min_length=1)


class CellRelation(BaseModel):
    model_config = ConfigDict(extra="allow")

    target: CellCoordinate
    operand_cells: list[CellCoordinate] = Field(min_length=1)


class CellRelationSumSpec(ProfileCheckSpec):
    type: Literal["cell_relation_sum"]
    comparisons: list[CellRelation] = Field(min_length=1)


class ArithmeticTerm(BaseModel):
    model_config = ConfigDict(extra="allow")

    column: int = Field(ge=0)
    op: Literal["+", "-"]


class RowArithmeticSpec(ProfileCheckSpec):
    type: Literal["row_arithmetic"]
    target_column: int = Field(ge=0)
    terms: list[ArithmeticTerm] = Field(min_length=1)
    row_indices: list[int] = Field(default_factory=list)
    row_scope: Literal["fixed", "all_data_rows", "year_rows", "year_first_occurrence", "year_range"] = "fixed"
    year_min: int | None = None
    year_max: int | None = None


class RowRatioSpec(ProfileCheckSpec):
    type: Literal["row_ratio"]
    target_column: int = Field(ge=0)
    numerator_column: int = Field(ge=0)
    denominator_column: int | None = Field(default=None, ge=0)
    denominator_columns: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_denominator(self) -> RowRatioSpec:
        if self.denominator_column is None and not self.denominator_columns:
            raise ValueError("denominator_column 또는 denominator_columns가 필요합니다.")
        return self


class ColumnShareRatioSpec(ProfileCheckSpec):
    type: Literal["column_share_ratio"]
    target_column: int = Field(ge=0)
    numerator_column: int = Field(ge=0)
    denominator_row: int = Field(ge=0)
    denominator_column: int | None = Field(default=None, ge=0)


class RowRatioByRowsSpec(ProfileCheckSpec):
    type: Literal["row_ratio_by_rows"]
    target_row: int = Field(ge=0)
    numerator_row: int = Field(ge=0)
    denominator_row: int | None = Field(default=None, ge=0)
    denominator_rows: list[int] = Field(default_factory=list)
    columns: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def require_denominator(self) -> RowRatioByRowsSpec:
        if self.denominator_row is None and not self.denominator_rows:
            raise ValueError("denominator_row 또는 denominator_rows가 필요합니다.")
        return self


class WeightedAverageSpec(ProfileCheckSpec):
    type: Literal["weighted_average"]
    target_row: int = Field(ge=0)
    target_column: int = Field(ge=0)
    operand_rows: list[int] = Field(min_length=1)
    value_column: int = Field(ge=0)
    weight_column: int = Field(ge=0)


class YearRowPair(BaseModel):
    model_config = ConfigDict(extra="allow")

    target_row: int = Field(ge=0)
    source_row: int = Field(ge=0)


class RowYearOverYearSpec(ProfileCheckSpec):
    type: Literal["row_year_over_year_rate", "row_year_over_year_change_amount"]
    target_row: int | None = Field(default=None, ge=0)
    source_row: int | None = Field(default=None, ge=0)
    row_pairs: list[YearRowPair] = Field(default_factory=list)
    columns: list[int] = Field(min_length=2)

    @model_validator(mode="after")
    def require_rows(self) -> RowYearOverYearSpec:
        if not self.row_pairs and (self.target_row is None or self.source_row is None):
            raise ValueError("target/source 행 또는 row_pairs가 필요합니다.")
        return self


class YearRowsChangeSpec(ProfileCheckSpec):
    type: Literal["year_rows_change_rate", "year_rows_change_amount"]
    value_column: int = Field(ge=0)
    row_indices: list[int] = Field(default_factory=list)
    row_scope: Literal["fixed", "year_rows", "year_range"] = "fixed"
    year_min: int | None = None
    year_max: int | None = None
    rate_column: int | None = Field(default=None, ge=0)
    change_column: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_result_column(self) -> YearRowsChangeSpec:
        if self.row_scope == "fixed" and len(self.row_indices) < 2:
            raise ValueError("고정 행 범위에는 row_indices가 2개 이상 필요합니다.")
        if self.type == "year_rows_change_rate" and self.rate_column is None:
            raise ValueError("rate_column이 필요합니다.")
        if self.type == "year_rows_change_amount" and self.change_column is None:
            raise ValueError("change_column이 필요합니다.")
        return self


class RowGrowthRateSpec(ProfileCheckSpec):
    type: Literal["row_growth_rate"]
    target_column: int = Field(ge=0)
    current_column: int = Field(ge=0)
    previous_column: int = Field(ge=0)


class CrossTableRowSumSpec(ProfileCheckSpec):
    type: Literal["cross_table_row_sum"]
    source_table_code: str = Field(min_length=1)
    target_column: int = Field(ge=0)
    operand_columns: list[int] = Field(default_factory=list)
    source_column: int | None = Field(default=None, ge=0)
    source_columns: list[int] = Field(default_factory=list)


class CrossTableWeightedAverageSpec(ProfileCheckSpec):
    type: Literal["cross_table_weighted_average"]
    source_table_code: str = Field(min_length=1)
    target_row: int = Field(ge=0)
    target_column: int = Field(ge=0)
    value_column: int = Field(ge=0)
    row_pairs: list[dict[str, Any]] = Field(min_length=1)


class GenericExecutableSpec(ProfileCheckSpec):
    """Typed envelope for less common executors with table-specific payloads."""

    supported_types: ClassVar[frozenset[str]] = frozenset(
        {
            "growth_rate_scan",
            "outlier_columns",
            "cross_table_cell_match",
            "cross_table_weighted_average",
        }
    )

    @model_validator(mode="after")
    def require_supported_type(self) -> GenericExecutableSpec:
        if self.type not in self.supported_types:
            raise ValueError(f"지원하지 않는 검수 명세 유형입니다: {self.type}")
        return self


SPEC_MODELS: dict[str, type[ProfileCheckSpec]] = {
    "metadata_required": MetadataRequiredSpec,
    "unit_required": MetadataRequiredSpec,
    "row_sum": RowSumSpec,
    "column_sum": ColumnSumSpec,
    "region_total": ColumnSumSpec,
    "cell_sum": CellSumSpec,
    "cell_relation_sum": CellRelationSumSpec,
    "row_arithmetic": RowArithmeticSpec,
    "row_ratio": RowRatioSpec,
    "column_share_ratio": ColumnShareRatioSpec,
    "row_ratio_by_rows": RowRatioByRowsSpec,
    "weighted_average": WeightedAverageSpec,
    "row_year_over_year_rate": RowYearOverYearSpec,
    "row_year_over_year_change_amount": RowYearOverYearSpec,
    "year_rows_change_rate": YearRowsChangeSpec,
    "year_rows_change_amount": YearRowsChangeSpec,
    "row_growth_rate": RowGrowthRateSpec,
    "cross_table_row_sum": CrossTableRowSumSpec,
    "cross_table_weighted_average": CrossTableWeightedAverageSpec,
    "growth_rate_scan": GenericExecutableSpec,
    "outlier_columns": GenericExecutableSpec,
    "cross_table_cell_match": GenericExecutableSpec,
}


@dataclass(frozen=True)
class ProfileSpecError:
    index: int
    rule_id: str
    rule_type: str
    message: str
    spec: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "rule_id": self.rule_id,
            "rule_type": self.rule_type,
            "message": self.message,
            "spec": self.spec,
        }


@dataclass(frozen=True)
class ProfileSpecValidation:
    valid_specs: list[dict[str, Any]]
    errors: list[ProfileSpecError]


def validate_profile_specs(
    specs: list[Any],
    *,
    table: ValidationTable | None = None,
) -> ProfileSpecValidation:
    valid_specs: list[dict[str, Any]] = []
    errors: list[ProfileSpecError] = []

    for index, raw_spec in enumerate(specs):
        if not isinstance(raw_spec, dict):
            errors.append(
                ProfileSpecError(index, "", "", "검수 명세가 객체 형식이 아닙니다.", {"value": raw_spec})
            )
            continue

        spec = dict(raw_spec)
        rule_id = str(spec.get("id") or "")
        rule_type = str(spec.get("type") or "")
        if (
            spec.get("execute") is False
            or rule_type in LEGACY_NON_EXECUTABLE_SPEC_TYPES
        ) and rule_type not in SUPPORTED_PROFILE_SPEC_TYPES:
            valid_specs.append(spec)
            continue

        model = SPEC_MODELS.get(rule_type)
        if model is None:
            errors.append(
                ProfileSpecError(index, rule_id, rule_type, f"지원하지 않는 검수 유형입니다: {rule_type}", spec)
            )
            continue

        try:
            parsed = model.model_validate(spec)
        except ValidationError as error:
            errors.append(
                ProfileSpecError(index, rule_id, rule_type, concise_validation_error(error), spec)
            )
            continue

        normalized = parsed.model_dump(mode="json", exclude_none=True)
        if table is not None:
            coordinate_error = validate_profile_coordinates(table, normalized)
            if coordinate_error:
                errors.append(
                    ProfileSpecError(index, rule_id, rule_type, coordinate_error, spec)
                )
                continue
        valid_specs.append(normalized)

    return ProfileSpecValidation(valid_specs=valid_specs, errors=errors)


def validate_profile_coordinates(
    table: ValidationTable,
    spec: dict[str, Any],
) -> str | None:
    row_limit = len(table.matrix)
    column_limit = column_count(table)
    is_cross_table = str(spec.get("type") or "").startswith("cross_table_")

    def visit(value: Any, path: str) -> str | None:
        if isinstance(value, dict):
            for key, child in value.items():
                if is_cross_table and (
                    key.startswith("source_")
                    or key in {"source_columns", "weight_row"}
                ):
                    continue
                if isinstance(child, int):
                    if key in {"row", "target_row", "source_row", "value_row", "weight_row"} or key.endswith("_row"):
                        if not 0 <= child < row_limit:
                            return f"{path}{key}={child} 행 좌표가 표 범위를 벗어났습니다."
                    if key in {"column", "target_column", "source_column", "value_column", "weight_column"} or key.endswith("_column"):
                        if not 0 <= child < column_limit:
                            return f"{path}{key}={child} 열 좌표가 표 범위를 벗어났습니다."
                if isinstance(child, list):
                    if key.endswith("_rows") or key == "row_indices":
                        for item in child:
                            if isinstance(item, int) and not 0 <= item < row_limit:
                                return f"{path}{key}의 {item} 행 좌표가 표 범위를 벗어났습니다."
                    if key.endswith("_columns") or key == "columns":
                        for item in child:
                            if isinstance(item, int) and not 0 <= item < column_limit:
                                return f"{path}{key}의 {item} 열 좌표가 표 범위를 벗어났습니다."
                nested_error = visit(child, f"{path}{key}.")
                if nested_error:
                    return nested_error
        elif isinstance(value, list):
            for index, child in enumerate(value):
                nested_error = visit(child, f"{path}{index}.")
                if nested_error:
                    return nested_error
        return None

    return visit(spec, "")


def concise_validation_error(error: ValidationError) -> str:
    messages = []
    for item in error.errors(include_url=False):
        location = ".".join(str(part) for part in item.get("loc", ()))
        message = str(item.get("msg") or "올바르지 않은 값")
        messages.append(f"{location}: {message}" if location else message)
    return "; ".join(messages[:4])
