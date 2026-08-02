from __future__ import annotations

from pydantic import BaseModel, Field


class ReproductionReportOption(BaseModel):
    id: int
    year: int
    title: str
    is_archived: bool = False


class ReproductionPeriodRule(BaseModel):
    mode: str
    count: int = 1
    first_period: str = ""
    last_period: str = ""
    target_period: str = ""
    anchor: str = ""


class ReproductionSourceCandidate(BaseModel):
    dataset_id: int
    external_id: str
    title: str
    title_similarity: float = 0
    value_coverage: float = 0
    header_coverage: float = 0
    has_target_period: bool = False


class ReproductionTableAnalysis(BaseModel):
    table_id: int
    code: str
    title: str
    table_order: int
    mapping_status: str
    generation_status: str
    materializer: str
    source_dataset_id: int | None = None
    source_external_id: str = ""
    source_title: str = ""
    match_method: str = ""
    confidence: float = 0
    reason: str = ""
    period_rule: ReproductionPeriodRule
    candidates: list[ReproductionSourceCandidate] = Field(default_factory=list)
    recipe_status: str = ""
    comparison_status: str = ""
    compared_cell_count: int = 0
    mismatch_count: int = 0
    comparison_error: str = ""


class ReproductionSummary(BaseModel):
    total_tables: int = 0
    mapped_tables: int = 0
    review_tables: int = 0
    unmapped_tables: int = 0
    basic_recipe_candidates: int = 0
    custom_recipe_required: int = 0
    draft_recipes: int = 0


class ReproductionBuildSummary(BaseModel):
    id: int
    report_id: int
    report_year: int
    target_data_year: int
    status: str
    total_tables: int = 0
    exact_tables: int = 0
    mismatch_tables: int = 0
    source_difference_tables: int = 0
    carried_forward_tables: int = 0
    static_tables: int = 0
    empty_tables: int = 0
    deleted_tables: int = 0
    source_missing_tables: int = 0
    unavailable_tables: int = 0
    recipe_required_tables: int = 0
    mapping_review_tables: int = 0
    compared_cells: int = 0
    mismatch_cells: int = 0
    source_difference_cells: int = 0
    created_at: str = ""
    completed_at: str = ""


class YearbookReproductionOverview(BaseModel):
    report_id: int
    report_year: int
    report_title: str
    target_data_period: str
    summary: ReproductionSummary
    latest_build: ReproductionBuildSummary | None = None
    available_reports: list[ReproductionReportOption]
    tables: list[ReproductionTableAnalysis]


class RecipeBootstrapResult(BaseModel):
    report_id: int
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    mapped: int = 0
    review_required: int = 0
