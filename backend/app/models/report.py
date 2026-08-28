from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.enums import (
    HighlightRole,
    HighlightScope,
    JobStatus,
    LanguageReviewStatus,
    ProfileStatus,
    Severity,
    TableStatus,
    ValidationStatus,
)

class Metric(BaseModel):
    label: str
    value: str
    caption: str | None = None
    tone: Literal["neutral", "blue", "green", "red", "amber"] = "neutral"


class ColumnDefinition(BaseModel):
    key: str
    label: str
    label_en: str | None = None
    header_path: list[str] = Field(default_factory=list)
    header_path_en: list[str] = Field(default_factory=list)
    align: Literal["left", "right", "center"] = "right"
    width: str | None = None
    source_col_index: int | None = None
    source_col_indexes: list[int] = Field(default_factory=list)
    footnote_marker: str = ""


class ValidationHighlightCell(BaseModel):
    row_index: int
    col_index: int
    role: HighlightRole = HighlightRole.RELATED


class ValidationHighlightRow(BaseModel):
    row_index: int
    role: HighlightRole = HighlightRole.RELATED


class ValidationIssue(BaseModel):
    id: str
    rule_id: str | None = None
    type: str
    location: str
    row_index: int | None = None
    col_index: int | None = None
    current_value: str
    expected_value: str | None = None
    difference: str | None = None
    status: ValidationStatus | str = ValidationStatus.NEEDS_REVIEW
    severity: Severity = Severity.WARNING
    detail: str
    formula: str | None = None
    display_group_key: str | None = None
    highlight_scope: HighlightScope = HighlightScope.NONE
    highlight_cells: list[ValidationHighlightCell] = Field(default_factory=list)
    highlight_rows: list[ValidationHighlightRow] = Field(default_factory=list)
    focus_cell: ValidationHighlightCell | None = None


class ChangeItem(BaseModel):
    id: str
    category: str
    item: str
    previous: str
    current: str
    status: str


class VisualizationSeries(BaseModel):
    label: str
    value: float
    previous: float | None = None


class Visualization(BaseModel):
    id: str
    title: str
    subtitle: str | None = None
    kind: Literal["bar", "line", "rank"]
    unit: str
    data: list[VisualizationSeries]


class TableMetadata(BaseModel):
    original_file: str
    sheet_name: str
    note: str
    source: str
    source_department: str = ""
    source_officer: str = ""
    source_extension: str = ""
    source_reference: str = ""
    base_date: str
    base_date_display: str = ""
    unit_display: str = ""
    extracted_at: str
    header_count: int = 0


class TableHierarchyItem(BaseModel):
    code: str
    title: str
    title_en: str | None = None


class StatTablePart(BaseModel):
    id: str
    code: str
    title: str
    title_en: str
    part_label: str
    unit: str
    status: TableStatus
    status_label: str
    updated_at: str
    columns: list[ColumnDefinition]
    rows: list[dict[str, Any]]
    checks: list[ValidationIssue]
    changes: list[ChangeItem]
    visualizations: list[Visualization]
    metadata: TableMetadata
    is_test_table: bool = False
    generation_status: str = ""
    generation_status_label: str = ""
    generation_message: str = ""
    incremental_source_key: str = ""
    incremental_match_method: str = ""
    incremental_confidence: float = 0
    incremental_reason_code: str = ""
    incremental_evidence: dict[str, Any] = Field(default_factory=dict)
    incremental_candidates: list[dict[str, Any]] = Field(default_factory=list)
    incremental_confirmed_by_user: bool = False
    update_mode: str = ""
    source_dataset_title: str = ""
    validation_stale: bool = False


class StatTable(BaseModel):
    id: str
    code: str
    title: str
    title_en: str
    section_title: str
    section_title_en: str
    domain: str
    unit: str
    sheet_name: str
    status: TableStatus
    status_label: str
    year_range: str
    updated_at: str
    theme: Literal["blue", "red", "green"]
    part_label: str | None = None
    hierarchy: list[TableHierarchyItem] = Field(default_factory=list)
    parts: list[StatTablePart] = Field(default_factory=list)
    columns: list[ColumnDefinition]
    rows: list[dict[str, Any]]
    summary: list[str]
    key_figures: list[Metric]
    checks: list[ValidationIssue]
    changes: list[ChangeItem]
    visualizations: list[Visualization]
    metadata: TableMetadata
    is_test_table: bool = False
    generation_status: str = ""
    generation_status_label: str = ""
    generation_message: str = ""
    incremental_source_key: str = ""
    incremental_match_method: str = ""
    incremental_confidence: float = 0
    incremental_reason_code: str = ""
    incremental_evidence: dict[str, Any] = Field(default_factory=dict)
    incremental_candidates: list[dict[str, Any]] = Field(default_factory=list)
    incremental_confirmed_by_user: bool = False
    update_mode: str = ""
    source_dataset_title: str = ""
    validation_stale: bool = False


class StatTableSummary(BaseModel):
    """List-view projection that deliberately excludes table cells."""

    id: str
    code: str
    title: str
    title_en: str
    section_title: str
    domain: str
    status: TableStatus
    status_label: str
    theme: Literal["blue", "red", "green"]
    part_count: int = 0
    summary: list[str] = Field(default_factory=list)
    key_figures: list[Metric] = Field(default_factory=list)
    checks: list[ValidationIssue] = Field(default_factory=list)
    validated_types: list[str] = Field(default_factory=list)
    is_test_table: bool = False
    generation_status: str = ""
    generation_status_label: str = ""
    generation_message: str = ""
    incremental_source_key: str = ""
    incremental_match_method: str = ""
    incremental_confidence: float = 0
    incremental_reason_code: str = ""
    incremental_evidence: dict[str, Any] = Field(default_factory=dict)
    incremental_candidates: list[dict[str, Any]] = Field(default_factory=list)
    incremental_confirmed_by_user: bool = False
    update_mode: str = ""
    source_dataset_title: str = ""
    validation_stale: bool = False


class TableDownloadCatalogItem(BaseModel):
    """Minimal table identity used when choosing an Excel download."""

    id: str
    code: str
    title: str


class ReportSummary(BaseModel):
    report_id: int | None = None
    file_name: str
    base_year: str
    total_tables: int
    normal_count: int
    needs_review_count: int
    suspected_error_count: int
    issue_counts: dict[str, int] = Field(default_factory=dict)
    is_test_report: bool = False
    validation_available: bool = True
    generation_counts: dict[str, int] = Field(default_factory=dict)
    origin_kind: str = ""
    base_report_id: int | None = None
    validation_scope: Literal["full", "changed_tables", "selected", "shared", "none"] = "full"
    changed_table_count: int = 0
    unchanged_table_count: int = 0
    selected_validation_keys: list[str] = Field(default_factory=list)
    reused_report_count: int = 0
    reused_table_count: int = 0
    reused_check_count: int = 0


class ReportOption(BaseModel):
    id: int
    year: int
    title: str
    file_name: str
    imported_at: str
    table_count: int
    kind: Literal["published", "test", "template"] = "published"


class ReportDeleteResult(BaseModel):
    report_id: int
    title: str
    table_count: int = 0
    validation_run_count: int = 0


class PressInsight(BaseModel):
    id: str
    title: str
    body: str
    table_id: str
    tone: Literal["neutral", "increase", "risk", "notable"] = "neutral"


class ReportPayload(BaseModel):
    summary: ReportSummary
    tables: list[StatTable]
    press_insights: list[PressInsight]
    available_reports: list[ReportOption] = Field(default_factory=list)
    available_templates: list[ReportOption] = Field(default_factory=list)


class ReportOverviewPayload(BaseModel):
    summary: ReportSummary
    tables: list[StatTableSummary]
    press_insights: list[PressInsight]
    available_reports: list[ReportOption] = Field(default_factory=list)
    available_templates: list[ReportOption] = Field(default_factory=list)


class ValidationCatalogItem(BaseModel):
    key: str
    label: str
    order: int
    default_visible: bool = True
    default_status: str
    default_severity: str
    description: str


class ValidationProfileSummary(BaseModel):
    id: int
    table_code: str
    table_title: str
    structure_signature: str
    table_type: str
    status: ProfileStatus
    source: str
    rules_count: int
    requires_llm_review: bool = False
    notes: str
    created_at: str
    updated_at: str
    approved_at: str | None = None
    approved_by: str | None = None


class ValidationProfileApprovalRequest(BaseModel):
    approved_by: str = "담당자"


class ValidationRunResult(BaseModel):
    run_id: int
    report_id: int
    tables: int
    issues: int
    language_candidates: int = 0
    language_pending: int = 0
    language_reused: int = 0
    language_status: LanguageReviewStatus = LanguageReviewStatus.PENDING
    selected_rule_keys: list[str] = Field(default_factory=list)
    reused_report_count: int = 0
    reused_table_count: int = 0
    reused_check_count: int = 0
    cancelled: bool = False


class ValidationJob(BaseModel):
    id: int
    report_id: int
    status: Literal["queued", "running", "completed", "stopped", "failed"]
    current_stage: str
    progress_percent: int = 0
    completed_units: int = 0
    total_units: int = 0
    cancel_requested: bool = False
    result: ValidationRunResult | None = None
    error_message: str = ""
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None


class ValidationReuseRunOption(BaseModel):
    """One completed validation execution that may be selected as a reuse source."""

    id: int
    report_id: int
    report_year: int
    report_title: str
    completed_at: str
    issue_count: int = 0
    normal_count: int = 0
    needs_review_count: int = 0
    suspected_error_count: int = 0
    scope_kind: str = "full"
    selected_rule_keys: list[str] = Field(default_factory=list)


class ValidationRunRequest(BaseModel):
    selected_rule_keys: list[str] = Field(default_factory=list)
    reuse_existing: bool = True
    # ``include_llm`` is kept for older API clients.  New clients send the two
    # independent switches below so calculation-profile drafting never forces
    # a full spelling/translation pass (and vice versa).
    include_llm: bool = False
    include_profile_llm: bool | None = None
    include_language_llm: bool | None = None
    source_validation_run_id: int | None = Field(default=None, gt=0)


class ReportProcessingJob(BaseModel):
    id: int
    report_id: int | None = None
    run_id: int | None = None
    source_file_name: str
    source_file_path: str
    source_storage: str = "local"
    source_object_key: str = ""
    source_file_hash: str = ""
    source_file_size: int = 0
    source_type: str
    report_year: int
    report_title: str
    options_json: str
    status: JobStatus
    current_stage: str
    progress_percent: int = 0
    attempt_count: int = 0
    error_message: str = ""
    result_json: str = "{}"
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    updated_at: str
    stages: list[dict] = Field(default_factory=list)
