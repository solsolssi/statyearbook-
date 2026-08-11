export type TableStatus = "normal" | "needs_review" | "suspected_error";
export type Severity = "info" | "warning" | "critical";
export type Tone = "neutral" | "blue" | "green" | "red" | "amber";

export interface Metric {
  label: string;
  value: string;
  caption?: string;
  tone: Tone;
}

export interface ColumnDefinition {
  key: string;
  label: string;
  label_en?: string;
  align: "left" | "right" | "center";
  width?: string;
  source_col_index?: number;
  source_col_indexes?: number[];
  footnote_marker?: string;
}

export interface ValidationHighlightCell {
  row_index: number;
  col_index: number;
  role: "target" | "related";
}

export interface ValidationHighlightRow {
  row_index: number;
  role: "target" | "related";
}

export interface ValidationIssue {
  id: string;
  rule_id?: string;
  type: string;
  location: string;
  row_index?: number;
  col_index?: number;
  current_value: string;
  expected_value?: string;
  difference?: string;
  status: string;
  severity: Severity;
  detail: string;
  formula?: string;
  display_group_key?: string;
  highlight_scope?: "none" | "metadata" | "cell" | "header" | "row" | "column";
  highlight_cells?: ValidationHighlightCell[];
  highlight_rows?: ValidationHighlightRow[];
  focus_cell?: ValidationHighlightCell | null;
}

export interface ChangeItem {
  id: string;
  category: string;
  item: string;
  previous: string;
  current: string;
  status: string;
}

export interface VisualizationSeries {
  label: string;
  value: number;
  previous?: number;
}

export interface Visualization {
  id: string;
  title: string;
  subtitle?: string;
  kind: "bar" | "line" | "rank";
  unit: string;
  data: VisualizationSeries[];
}

export interface TableMetadata {
  original_file: string;
  sheet_name: string;
  note: string;
  source: string;
  source_department: string;
  source_officer: string;
  source_extension: string;
  source_reference: string;
  base_date: string;
  base_date_display: string;
  unit_display: string;
  extracted_at: string;
  header_count?: number;
}

export interface TableHierarchyItem {
  code: string;
  title: string;
  title_en?: string;
}

export interface StatTablePart {
  id: string;
  code: string;
  title: string;
  title_en: string;
  part_label: string;
  unit: string;
  status: TableStatus;
  status_label: string;
  updated_at: string;
  columns: ColumnDefinition[];
  rows: Array<Record<string, string | number>>;
  checks: ValidationIssue[];
  changes: ChangeItem[];
  visualizations: Visualization[];
  metadata: TableMetadata;
  is_test_table?: boolean;
  generation_status?: string;
  generation_status_label?: string;
  generation_message?: string;
  update_mode?: string;
  source_dataset_title?: string;
}

export interface StatTable {
  id: string;
  code: string;
  title: string;
  title_en: string;
  section_title: string;
  section_title_en: string;
  domain: string;
  unit: string;
  sheet_name: string;
  status: TableStatus;
  status_label: string;
  year_range: string;
  updated_at: string;
  theme: "blue" | "red" | "green";
  part_label?: string;
  hierarchy: TableHierarchyItem[];
  parts: StatTablePart[];
  columns: ColumnDefinition[];
  rows: Array<Record<string, string | number>>;
  summary: string[];
  key_figures: Metric[];
  checks: ValidationIssue[];
  changes: ChangeItem[];
  visualizations: Visualization[];
  metadata: TableMetadata;
  is_test_table?: boolean;
  generation_status?: string;
  generation_status_label?: string;
  generation_message?: string;
  update_mode?: string;
  source_dataset_title?: string;
}

export interface StatTableSummary {
  id: string;
  code: string;
  title: string;
  title_en: string;
  section_title: string;
  domain: string;
  status: TableStatus;
  status_label: string;
  theme: "blue" | "red" | "green";
  part_count: number;
  summary: string[];
  key_figures: Metric[];
  checks: ValidationIssue[];
  is_test_table?: boolean;
  generation_status?: string;
  generation_status_label?: string;
  generation_message?: string;
  update_mode?: string;
  source_dataset_title?: string;
}

export interface ReportSummary {
  report_id: number | null;
  file_name: string;
  base_year: string;
  total_tables: number;
  normal_count: number;
  needs_review_count: number;
  suspected_error_count: number;
  issue_counts: Record<string, number>;
  is_test_report?: boolean;
  validation_available?: boolean;
  generation_counts?: Record<string, number>;
  origin_kind?: string;
  base_report_id?: number | null;
  validation_scope?: "full" | "changed_tables" | "selected" | "shared" | "none";
  changed_table_count?: number;
  unchanged_table_count?: number;
  selected_validation_keys?: string[];
  reused_report_count?: number;
  reused_table_count?: number;
  reused_check_count?: number;
}

export interface ReportOption {
  id: number;
  year: number;
  title: string;
  file_name: string;
  imported_at: string;
  table_count: number;
  kind?: "published" | "test" | "template";
}

export interface ReportDeleteResult {
  report_id: number;
  title: string;
  table_count: number;
  validation_run_count: number;
}

export interface ValidationReuseRunOption {
  id: number;
  report_id: number;
  report_year: number;
  report_title: string;
  completed_at: string;
  issue_count: number;
  normal_count: number;
  needs_review_count: number;
  suspected_error_count: number;
  scope_kind: string;
  selected_rule_keys: string[];
}

export interface PressInsight {
  id: string;
  title: string;
  body: string;
  table_id: string;
  tone: "neutral" | "increase" | "risk" | "notable";
}

export interface ReportPayload {
  summary: ReportSummary;
  tables: StatTableSummary[];
  press_insights: PressInsight[];
  available_reports: ReportOption[];
  available_templates: ReportOption[];
}

export interface ValidationCatalogItem {
  key: string;
  label: string;
  order: number;
  default_visible: boolean;
  default_status: string;
  default_severity: string;
  description: string;
}

export interface SourceStatisticsSummary {
  total_datasets: number;
  datasets_with_values: number;
  total_values: number;
  earliest_period: string;
  latest_period: string;
  full_imported_at: string;
  incremental_imported_at: string;
}

export interface SourceStatisticListItem {
  external_id: string;
  title: string;
  source_kind: string;
  directory: string;
  department: string;
  item_count: number;
  value_count: number;
  period_count: number;
  earliest_period: string;
  latest_period: string;
}

export interface SourceStatisticsOverview {
  summary: SourceStatisticsSummary;
  datasets: SourceStatisticListItem[];
}

export interface SourceStatisticPeriod {
  value: string;
  label: string;
  row_count: number;
}

export interface SourceStatisticColumn {
  key: string;
  label: string;
  data_type: string;
  item_data_no: number;
  align: "left" | "right" | "center";
}

export interface SourceStatisticMetadata {
  source_kind: string;
  storage_table: string;
  directory: string;
  subdirectory: string;
  input_status: string;
  department: string;
  officer_name: string;
  input_period: string;
  data_reference_time: string;
}

export interface SourceStatisticDetail {
  external_id: string;
  title: string;
  selected_period: string;
  periods: SourceStatisticPeriod[];
  columns: SourceStatisticColumn[];
  rows: Array<Record<string, string | number>>;
  metadata: SourceStatisticMetadata;
  total_rows: number;
}

export interface SourceDataImportResult {
  mode: "append_year";
  base_report_id: number;
  target_year: number;
  batch_id: number;
  datasets: number;
  items: number;
  values: number;
  inserted_values: number;
  updated_values: number;
  unchanged_values: number;
  reused: boolean;
  generated_report_id: number;
  reproduction_run_id: number;
  source_snapshot_id: number;
  generated_table_count: number;
  review_table_count: number;
  deleted_table_count: number;
  new_table_count: number;
}

export interface ReportTableDifference {
  table_code: string;
  change_type: "matching" | "modified" | "added" | "deleted";
  changed_cell_count: number;
  cell_differences: Array<{
    row_index: number;
    col_index: number;
    left_value: string;
    right_value: string;
  }>;
}

export interface ReportComparisonSummary {
  id: number;
  left_report_id: number;
  right_report_id: number;
  total_table_count: number;
  matching_table_count: number;
  changed_table_count: number;
  added_table_count: number;
  deleted_table_count: number;
  changed_cell_count: number;
  tables: ReportTableDifference[];
}

export interface ReproductionReportOption {
  id: number;
  year: number;
  title: string;
  is_archived: boolean;
}

export interface ReproductionPeriodRule {
  mode: "latest_n" | "single_period" | string;
  count: number;
  first_period: string;
  last_period: string;
  target_period: string;
  anchor: string;
}

export interface ReproductionSourceCandidate {
  dataset_id: number;
  external_id: string;
  title: string;
  title_similarity: number;
  value_coverage: number;
  header_coverage: number;
  has_target_period: boolean;
}

export interface ReproductionTableAnalysis {
  table_id: number;
  code: string;
  title: string;
  table_order: number;
  mapping_status: "mapped" | "review" | "unmapped";
  generation_status: "basic_recipe" | "custom_recipe";
  materializer: string;
  source_dataset_id: number | null;
  source_external_id: string;
  source_title: string;
  match_method: string;
  confidence: number;
  reason: string;
  period_rule: ReproductionPeriodRule;
  candidates: ReproductionSourceCandidate[];
  recipe_status: string;
  comparison_status: string;
  compared_cell_count: number;
  mismatch_count: number;
  comparison_error: string;
}

export interface ReproductionBuildSummary {
  id: number;
  report_id: number;
  report_year: number;
  target_data_year: number;
  status: string;
  total_tables: number;
  exact_tables: number;
  mismatch_tables: number;
  source_difference_tables: number;
  carried_forward_tables: number;
  static_tables: number;
  empty_tables: number;
  deleted_tables: number;
  source_missing_tables: number;
  unavailable_tables: number;
  recipe_required_tables: number;
  mapping_review_tables: number;
  compared_cells: number;
  mismatch_cells: number;
  source_difference_cells: number;
  created_at: string;
  completed_at: string;
}

export interface YearbookReproductionOverview {
  report_id: number;
  report_year: number;
  report_title: string;
  target_data_period: string;
  summary: {
    total_tables: number;
    mapped_tables: number;
    review_tables: number;
    unmapped_tables: number;
    basic_recipe_candidates: number;
    custom_recipe_required: number;
    draft_recipes: number;
  };
  latest_build: ReproductionBuildSummary | null;
  available_reports: ReproductionReportOption[];
  tables: ReproductionTableAnalysis[];
}
