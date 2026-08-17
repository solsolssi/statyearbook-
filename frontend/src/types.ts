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
  /** Header levels from the outer group to the leaf label. */
  header_path?: string[];
  header_path_en?: string[];
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

export interface IncrementalConnectionCandidate {
  source_key: string;
  title: string;
  score: number;
  title_score: number;
  structure_score: number;
  metadata_score: number;
  number_score: number;
}

export interface IncrementalConnectionItem {
  table_code: string;
  table_id: number | null;
  title: string;
  source_key: string;
  match_method: string;
  confidence: number;
  mapping_status: string;
  generation_status: string;
  generation_message: string;
  reason_code: string;
  evidence: Record<string, unknown>;
  candidates: IncrementalConnectionCandidate[];
  confirmed_by_user: boolean;
}

export interface IncrementalConnectionOverview {
  report_id: number;
  connections: IncrementalConnectionItem[];
  unmatched_increments: IncrementalConnectionItem[];
  ignored_increments: IncrementalConnectionItem[];
  summary: {
    total: number;
    connected: number;
    review: number;
    unmatched: number;
    deleted: number;
    identified_physical_tables: number;
  };
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
  incremental_source_key?: string;
  incremental_match_method?: string;
  incremental_confidence?: number;
  incremental_reason_code?: string;
  incremental_evidence?: Record<string, unknown>;
  incremental_candidates?: IncrementalConnectionCandidate[];
  incremental_confirmed_by_user?: boolean;
  update_mode?: string;
  source_dataset_title?: string;
  validation_stale?: boolean;
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
  incremental_source_key?: string;
  incremental_match_method?: string;
  incremental_confidence?: number;
  incremental_reason_code?: string;
  incremental_evidence?: Record<string, unknown>;
  incremental_candidates?: IncrementalConnectionCandidate[];
  incremental_confirmed_by_user?: boolean;
  update_mode?: string;
  source_dataset_title?: string;
  validation_stale?: boolean;
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
  incremental_source_key?: string;
  incremental_match_method?: string;
  incremental_confidence?: number;
  incremental_reason_code?: string;
  incremental_evidence?: Record<string, unknown>;
  incremental_candidates?: IncrementalConnectionCandidate[];
  incremental_confirmed_by_user?: boolean;
  update_mode?: string;
  source_dataset_title?: string;
  validation_stale?: boolean;
}

export interface StatisticEditAccess {
  table_id: string;
  code: string;
  title: string;
  source_officer: string;
  has_password: boolean;
  is_initial_password: boolean;
  updated_at: string;
}

export interface ReportEditAccess {
  report_id: number;
  year: number;
  title: string;
  statistics: StatisticEditAccess[];
}

export interface TableEditSession {
  access_token: string;
}

export interface EditableColumnPatch {
  source_col_indexes: number[];
  label: string;
  label_en: string;
  header_path?: string[];
  header_path_en?: string[];
  footnote_marker: string;
}

export interface EditableCellPatch {
  row_index: number;
  col_index: number;
  value: string;
  value_en: string;
  footnote_marker: string;
}

export interface EditableHierarchyPatch {
  kind: "domain" | "section";
  original_code: string;
  code: string;
  title: string;
  title_en: string;
}

export interface EditableTablePartPayload {
  id: string;
  code: string;
  title: string;
  title_en: string;
  unit: string;
  header_count: number;
  metadata: {
    base_date: string;
    note: string;
    source: string;
    source_department: string;
    source_officer: string;
    source_extension: string;
    source_reference: string;
  };
  columns: EditableColumnPatch[];
  cells: EditableCellPatch[];
  replace_structure: boolean;
  replace_rows: boolean;
}

export interface TableContentUpdatePayload {
  code: string;
  title: string;
  title_en: string;
  section_title: string;
  section_title_en: string;
  domain: string;
  hierarchy_patches: EditableHierarchyPatch[];
  deleted_part_ids: string[];
  parts: EditableTablePartPayload[];
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
