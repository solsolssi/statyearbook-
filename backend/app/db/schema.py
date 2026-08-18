import json
import re
from typing import Any

from app.db.connection import DB_PATH, DatabaseConnection
from app.validation.catalog import REQUIRED_RULE_DEFINITIONS


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    key TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS annual_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    title TEXT NOT NULL,
    source_file_name TEXT NOT NULL,
    source_file_path TEXT NOT NULL,
    file_hash TEXT NOT NULL UNIQUE,
    parse_warnings_json TEXT NOT NULL DEFAULT '[]',
    imported_at TEXT NOT NULL,
    is_archived INTEGER NOT NULL DEFAULT 0,
    is_template INTEGER NOT NULL DEFAULT 0,
    origin_kind TEXT NOT NULL DEFAULT 'uploaded',
    base_report_id INTEGER,
    layout_report_id INTEGER,
    FOREIGN KEY (base_report_id) REFERENCES annual_reports(id) ON DELETE SET NULL,
    FOREIGN KEY (layout_report_id) REFERENCES annual_reports(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS stat_tables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    title_en TEXT NOT NULL DEFAULT '',
    section_title TEXT NOT NULL DEFAULT '',
    section_title_en TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    base_date TEXT NOT NULL DEFAULT '',
    section_file TEXT NOT NULL DEFAULT '',
    table_order INTEGER NOT NULL DEFAULT 0,
    cell_range TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    extracted_at TEXT NOT NULL DEFAULT '',
    raw_context TEXT NOT NULL DEFAULT '',
    parse_warnings_json TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (report_id) REFERENCES annual_reports(id) ON DELETE CASCADE,
    UNIQUE (report_id, code)
);

CREATE TABLE IF NOT EXISTS stat_table_cells (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id INTEGER NOT NULL,
    row_index INTEGER NOT NULL,
    col_index INTEGER NOT NULL,
    text_value TEXT NOT NULL DEFAULT '',
    numeric_value REAL,
    is_header INTEGER NOT NULL DEFAULT 0,
    footnote_marker TEXT NOT NULL DEFAULT '',
    source_coordinate TEXT NOT NULL DEFAULT '',
    text_color TEXT NOT NULL DEFAULT '',
    parse_warnings_json TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (table_id) REFERENCES stat_tables(id) ON DELETE CASCADE,
    UNIQUE (table_id, row_index, col_index)
);

CREATE INDEX IF NOT EXISTS idx_stat_tables_report_order
ON stat_tables(report_id, table_order);

CREATE INDEX IF NOT EXISTS idx_stat_table_cells_table_position
ON stat_table_cells(table_id, row_index, col_index);

CREATE TABLE IF NOT EXISTS yearbook_edit_passwords (
    report_id INTEGER NOT NULL,
    table_key TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    password_iterations INTEGER NOT NULL,
    is_initial INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (report_id, table_key),
    FOREIGN KEY (report_id) REFERENCES annual_reports(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS yearbook_edit_sessions (
    token_hash TEXT PRIMARY KEY,
    report_id INTEGER NOT NULL,
    table_key TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (report_id) REFERENCES annual_reports(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_yearbook_edit_sessions_expiry
ON yearbook_edit_sessions(expires_at);

CREATE TABLE IF NOT EXISTS yearbook_manual_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    table_key TEXT NOT NULL,
    session_token_hash TEXT NOT NULL,
    changes_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (report_id) REFERENCES annual_reports(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_yearbook_manual_edits_table
ON yearbook_manual_edits(report_id, table_key, created_at DESC);

CREATE TABLE IF NOT EXISTS report_update_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    base_report_id INTEGER,
    report_id INTEGER NOT NULL,
    update_kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    changed_table_count INTEGER NOT NULL DEFAULT 0,
    unchanged_table_count INTEGER NOT NULL DEFAULT 0,
    added_table_count INTEGER NOT NULL DEFAULT 0,
    deleted_table_count INTEGER NOT NULL DEFAULT 0,
    changed_cell_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (base_report_id) REFERENCES annual_reports(id) ON DELETE SET NULL,
    FOREIGN KEY (report_id) REFERENCES annual_reports(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_report_update_batches_report
ON report_update_batches(report_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS report_update_table_diffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    table_code TEXT NOT NULL,
    base_table_id INTEGER,
    report_table_id INTEGER,
    change_type TEXT NOT NULL,
    metadata_changed INTEGER NOT NULL DEFAULT 0,
    changed_cell_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (batch_id) REFERENCES report_update_batches(id) ON DELETE CASCADE,
    FOREIGN KEY (base_table_id) REFERENCES stat_tables(id) ON DELETE SET NULL,
    FOREIGN KEY (report_table_id) REFERENCES stat_tables(id) ON DELETE SET NULL,
    UNIQUE (batch_id, table_code)
);

CREATE INDEX IF NOT EXISTS idx_report_update_table_diffs_batch
ON report_update_table_diffs(batch_id, change_type, table_code);

CREATE TABLE IF NOT EXISTS report_update_cell_diffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_diff_id INTEGER NOT NULL,
    row_index INTEGER NOT NULL,
    col_index INTEGER NOT NULL,
    previous_value TEXT NOT NULL DEFAULT '',
    current_value TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (table_diff_id) REFERENCES report_update_table_diffs(id) ON DELETE CASCADE,
    UNIQUE (table_diff_id, row_index, col_index)
);

CREATE TABLE IF NOT EXISTS report_comparison_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    left_report_id INTEGER NOT NULL,
    right_report_id INTEGER NOT NULL,
    total_table_count INTEGER NOT NULL DEFAULT 0,
    matching_table_count INTEGER NOT NULL DEFAULT 0,
    changed_table_count INTEGER NOT NULL DEFAULT 0,
    added_table_count INTEGER NOT NULL DEFAULT 0,
    deleted_table_count INTEGER NOT NULL DEFAULT 0,
    changed_cell_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (left_report_id) REFERENCES annual_reports(id) ON DELETE CASCADE,
    FOREIGN KEY (right_report_id) REFERENCES annual_reports(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS report_comparison_table_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    table_code TEXT NOT NULL,
    left_table_id INTEGER,
    right_table_id INTEGER,
    change_type TEXT NOT NULL,
    changed_cell_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES report_comparison_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (left_table_id) REFERENCES stat_tables(id) ON DELETE SET NULL,
    FOREIGN KEY (right_table_id) REFERENCES stat_tables(id) ON DELETE SET NULL,
    UNIQUE (run_id, table_code)
);

CREATE TABLE IF NOT EXISTS report_comparison_cell_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_result_id INTEGER NOT NULL,
    row_index INTEGER NOT NULL,
    col_index INTEGER NOT NULL,
    left_value TEXT NOT NULL DEFAULT '',
    right_value TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (table_result_id) REFERENCES report_comparison_table_results(id) ON DELETE CASCADE,
    UNIQUE (table_result_id, row_index, col_index)
);

CREATE TABLE IF NOT EXISTS generated_report_table_status (
    report_id INTEGER NOT NULL,
    table_id INTEGER NOT NULL,
    source_table_id INTEGER,
    generation_status TEXT NOT NULL DEFAULT '',
    generation_message TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (report_id, table_id),
    FOREIGN KEY (report_id) REFERENCES annual_reports(id) ON DELETE CASCADE,
    FOREIGN KEY (table_id) REFERENCES stat_tables(id) ON DELETE CASCADE,
    FOREIGN KEY (source_table_id) REFERENCES stat_tables(id) ON DELETE SET NULL
);

-- Increment files belong to the draft annual report that they produced.  They
-- are intentionally separate from the optional, whole-source ledger tables.
CREATE TABLE IF NOT EXISTS report_incremental_uploads (
    report_id INTEGER PRIMARY KEY,
    base_report_id INTEGER,
    target_year INTEGER NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    source_hash TEXT NOT NULL DEFAULT '',
    matcher_version INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (report_id) REFERENCES annual_reports(id) ON DELETE CASCADE,
    FOREIGN KEY (base_report_id) REFERENCES annual_reports(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS report_incremental_table_mappings (
    report_id INTEGER NOT NULL,
    table_code TEXT NOT NULL,
    source_key TEXT NOT NULL DEFAULT '',
    match_method TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0,
    mapping_status TEXT NOT NULL DEFAULT 'review',
    reason_code TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    candidates_json TEXT NOT NULL DEFAULT '[]',
    confirmed_by_user INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (report_id, table_code),
    FOREIGN KEY (report_id) REFERENCES annual_reports(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_report_incremental_mappings_key
ON report_incremental_table_mappings(report_id, source_key);

-- Cell-level provenance makes changing a manually selected increment key
-- reversible.  Only values written by the increment workflow are restored;
-- subsequent user edits are never overwritten during a remap.
CREATE TABLE IF NOT EXISTS report_incremental_cell_overlays (
    report_id INTEGER NOT NULL,
    table_id INTEGER NOT NULL,
    row_index INTEGER NOT NULL,
    col_index INTEGER NOT NULL,
    source_key TEXT NOT NULL DEFAULT '',
    base_text TEXT NOT NULL DEFAULT '',
    applied_text TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (report_id, table_id, row_index, col_index),
    FOREIGN KEY (report_id) REFERENCES annual_reports(id) ON DELETE CASCADE,
    FOREIGN KEY (table_id) REFERENCES stat_tables(id) ON DELETE CASCADE
);

-- A source M key is stable even when a publication number changes.  Recipes
-- learned from a completed edition record only layout behavior; they never
-- copy values from the browse-only statistical ledger.
CREATE TABLE IF NOT EXISTS report_incremental_update_recipes (
    source_key TEXT PRIMARY KEY,
    update_mode TEXT NOT NULL,
    retention_mode TEXT NOT NULL DEFAULT 'replace',
    window_size INTEGER NOT NULL DEFAULT 0,
    learned_from_report_id INTEGER,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (learned_from_report_id) REFERENCES annual_reports(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS series_import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file_name TEXT NOT NULL,
    source_file_path TEXT NOT NULL DEFAULT '',
    file_hash TEXT NOT NULL,
    import_kind TEXT NOT NULL,
    target_year INTEGER,
    status TEXT NOT NULL DEFAULT 'imported',
    summary_json TEXT NOT NULL DEFAULT '{}',
    error_message TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (file_hash, import_kind, target_year)
);

CREATE INDEX IF NOT EXISTS idx_series_import_batches_target
ON series_import_batches(target_year, imported_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS statistical_datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE,
    external_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT '',
    storage_table TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    introduced_batch_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (introduced_batch_id) REFERENCES series_import_batches(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_statistical_datasets_title
ON statistical_datasets(title, status);

CREATE TABLE IF NOT EXISTS statistical_dataset_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    structure_signature TEXT NOT NULL,
    header_row_count INTEGER NOT NULL DEFAULT 1,
    period_column INTEGER NOT NULL DEFAULT 0,
    dimension_columns_json TEXT NOT NULL DEFAULT '[]',
    columns_json TEXT NOT NULL DEFAULT '[]',
    source_batch_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dataset_id) REFERENCES statistical_datasets(id) ON DELETE CASCADE,
    FOREIGN KEY (source_batch_id) REFERENCES series_import_batches(id) ON DELETE RESTRICT,
    UNIQUE (dataset_id, structure_signature)
);

CREATE INDEX IF NOT EXISTS idx_statistical_dataset_versions_dataset
ON statistical_dataset_versions(dataset_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS statistical_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_version_id INTEGER NOT NULL,
    source_batch_id INTEGER NOT NULL,
    period TEXT NOT NULL,
    dimension_key TEXT NOT NULL DEFAULT '',
    dimension_values_json TEXT NOT NULL DEFAULT '[]',
    values_json TEXT NOT NULL DEFAULT '[]',
    source_sheet TEXT NOT NULL DEFAULT '',
    source_row_number INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dataset_version_id) REFERENCES statistical_dataset_versions(id) ON DELETE CASCADE,
    FOREIGN KEY (source_batch_id) REFERENCES series_import_batches(id) ON DELETE CASCADE,
    UNIQUE (dataset_version_id, source_batch_id, period, dimension_key)
);

CREATE INDEX IF NOT EXISTS idx_statistical_observations_lookup
ON statistical_observations(dataset_version_id, period, dimension_key, source_batch_id DESC);

CREATE TABLE IF NOT EXISTS statistical_dataset_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    item_id TEXT NOT NULL DEFAULT '',
    level INTEGER NOT NULL DEFAULT 0,
    item_data_no INTEGER NOT NULL,
    item_name TEXT NOT NULL DEFAULT '',
    data_type TEXT NOT NULL DEFAULT '',
    is_dummy INTEGER NOT NULL DEFAULT 0,
    input_required INTEGER NOT NULL DEFAULT 0,
    max_level INTEGER NOT NULL DEFAULT 0,
    is_leaf INTEGER NOT NULL DEFAULT 0,
    full_name TEXT NOT NULL DEFAULT '',
    display_order INTEGER NOT NULL DEFAULT 0,
    source_batch_id INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dataset_id) REFERENCES statistical_datasets(id) ON DELETE CASCADE,
    FOREIGN KEY (source_batch_id) REFERENCES series_import_batches(id) ON DELETE RESTRICT,
    UNIQUE (dataset_id, item_data_no)
);

CREATE INDEX IF NOT EXISTS idx_statistical_dataset_items_order
ON statistical_dataset_items(dataset_id, item_data_no);

CREATE TABLE IF NOT EXISTS statistical_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    data_cycle TEXT NOT NULL DEFAULT '',
    period TEXT NOT NULL,
    data_division TEXT NOT NULL DEFAULT '',
    item_data_no INTEGER NOT NULL,
    class_data_no INTEGER NOT NULL DEFAULT -1,
    data_value TEXT NOT NULL DEFAULT '',
    string_value TEXT NOT NULL DEFAULT '',
    comment_identifier TEXT NOT NULL DEFAULT '',
    comment_text TEXT NOT NULL DEFAULT '',
    english_comment_text TEXT NOT NULL DEFAULT '',
    write_state TEXT NOT NULL DEFAULT '',
    check_code TEXT NOT NULL DEFAULT '',
    verified INTEGER NOT NULL DEFAULT 0,
    verification_result TEXT NOT NULL DEFAULT '',
    source_sequence TEXT NOT NULL DEFAULT '',
    source_registered_at TEXT NOT NULL DEFAULT '',
    source_batch_id INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dataset_id) REFERENCES statistical_datasets(id) ON DELETE CASCADE,
    FOREIGN KEY (source_batch_id) REFERENCES series_import_batches(id) ON DELETE RESTRICT,
    UNIQUE (
        dataset_id, data_cycle, period, data_division,
        item_data_no, class_data_no
    )
);

CREATE INDEX IF NOT EXISTS idx_statistical_values_snapshot
ON statistical_values(dataset_id, period DESC, data_cycle, data_division, class_data_no, item_data_no);

CREATE TABLE IF NOT EXISTS statistical_value_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statistical_value_id INTEGER NOT NULL,
    replaced_by_batch_id INTEGER NOT NULL,
    data_value TEXT NOT NULL DEFAULT '',
    string_value TEXT NOT NULL DEFAULT '',
    comment_identifier TEXT NOT NULL DEFAULT '',
    comment_text TEXT NOT NULL DEFAULT '',
    english_comment_text TEXT NOT NULL DEFAULT '',
    write_state TEXT NOT NULL DEFAULT '',
    check_code TEXT NOT NULL DEFAULT '',
    verified INTEGER NOT NULL DEFAULT 0,
    verification_result TEXT NOT NULL DEFAULT '',
    source_batch_id INTEGER NOT NULL,
    archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (statistical_value_id) REFERENCES statistical_values(id) ON DELETE CASCADE,
    FOREIGN KEY (replaced_by_batch_id) REFERENCES series_import_batches(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_batch_id) REFERENCES series_import_batches(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_statistical_value_revisions_value
ON statistical_value_revisions(statistical_value_id, archived_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS statistical_dataset_item_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statistical_dataset_item_id INTEGER NOT NULL,
    replaced_by_batch_id INTEGER NOT NULL,
    item_id TEXT NOT NULL DEFAULT '',
    level INTEGER NOT NULL DEFAULT 0,
    item_name TEXT NOT NULL DEFAULT '',
    data_type TEXT NOT NULL DEFAULT '',
    is_dummy INTEGER NOT NULL DEFAULT 0,
    input_required INTEGER NOT NULL DEFAULT 0,
    max_level INTEGER NOT NULL DEFAULT 0,
    is_leaf INTEGER NOT NULL DEFAULT 0,
    full_name TEXT NOT NULL DEFAULT '',
    display_order INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    source_batch_id INTEGER NOT NULL,
    archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (statistical_dataset_item_id)
        REFERENCES statistical_dataset_items(id) ON DELETE CASCADE,
    FOREIGN KEY (replaced_by_batch_id)
        REFERENCES series_import_batches(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_batch_id)
        REFERENCES series_import_batches(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_statistical_dataset_item_revisions_item
ON statistical_dataset_item_revisions(
    statistical_dataset_item_id, archived_at DESC, id DESC
);

CREATE TABLE IF NOT EXISTS statistical_dataset_lifecycle_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    source_batch_id INTEGER NOT NULL,
    lifecycle_status TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dataset_id) REFERENCES statistical_datasets(id) ON DELETE CASCADE,
    FOREIGN KEY (source_batch_id)
        REFERENCES series_import_batches(id) ON DELETE CASCADE,
    UNIQUE (dataset_id, source_batch_id, lifecycle_status)
);

CREATE INDEX IF NOT EXISTS idx_statistical_dataset_lifecycle_events_batch
ON statistical_dataset_lifecycle_events(source_batch_id, dataset_id);

CREATE TABLE IF NOT EXISTS source_data_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER UNIQUE,
    parent_snapshot_id INTEGER,
    source_batch_id INTEGER NOT NULL,
    target_year INTEGER NOT NULL,
    snapshot_kind TEXT NOT NULL DEFAULT 'report',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (report_id) REFERENCES annual_reports(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_snapshot_id)
        REFERENCES source_data_snapshots(id) ON DELETE RESTRICT,
    FOREIGN KEY (source_batch_id)
        REFERENCES series_import_batches(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_source_data_snapshots_parent
ON source_data_snapshots(parent_snapshot_id, id);

CREATE TABLE IF NOT EXISTS source_snapshot_batches (
    snapshot_id INTEGER NOT NULL,
    source_batch_id INTEGER NOT NULL,
    precedence INTEGER NOT NULL,
    visible_through_year INTEGER,
    PRIMARY KEY (snapshot_id, source_batch_id),
    UNIQUE (snapshot_id, precedence),
    FOREIGN KEY (snapshot_id)
        REFERENCES source_data_snapshots(id) ON DELETE CASCADE,
    FOREIGN KEY (source_batch_id)
        REFERENCES series_import_batches(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_source_snapshot_batches_batch
ON source_snapshot_batches(source_batch_id, snapshot_id);

CREATE TABLE IF NOT EXISTS statistical_period_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id INTEGER NOT NULL,
    period TEXT NOT NULL,
    management_number TEXT NOT NULL DEFAULT '',
    subdirectory TEXT NOT NULL DEFAULT '',
    directory TEXT NOT NULL DEFAULT '',
    input_status TEXT NOT NULL DEFAULT '',
    department TEXT NOT NULL DEFAULT '',
    officer_name TEXT NOT NULL DEFAULT '',
    input_period TEXT NOT NULL DEFAULT '',
    data_reference_time TEXT NOT NULL DEFAULT '',
    source_batch_id INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (dataset_id) REFERENCES statistical_datasets(id) ON DELETE CASCADE,
    FOREIGN KEY (source_batch_id) REFERENCES series_import_batches(id) ON DELETE RESTRICT,
    UNIQUE (dataset_id, period)
);

CREATE INDEX IF NOT EXISTS idx_statistical_period_metadata_period
ON statistical_period_metadata(dataset_id, period DESC);

CREATE TABLE IF NOT EXISTS yearbook_table_recipes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_code TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    effective_from_year INTEGER NOT NULL,
    effective_to_year INTEGER,
    source_dataset_id INTEGER,
    materializer TEXT NOT NULL DEFAULT 'copy',
    config_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'draft',
    source_report_id INTEGER,
    source_table_id INTEGER,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at TEXT,
    approved_by TEXT,
    FOREIGN KEY (source_dataset_id) REFERENCES statistical_datasets(id) ON DELETE SET NULL,
    FOREIGN KEY (source_report_id) REFERENCES annual_reports(id) ON DELETE SET NULL,
    FOREIGN KEY (source_table_id) REFERENCES stat_tables(id) ON DELETE SET NULL,
    UNIQUE (table_code, revision)
);

CREATE INDEX IF NOT EXISTS idx_yearbook_table_recipes_effective
ON yearbook_table_recipes(table_code, effective_from_year, effective_to_year, status);

CREATE TABLE IF NOT EXISTS yearbook_table_update_policies (
    table_code TEXT PRIMARY KEY,
    update_mode TEXT NOT NULL DEFAULT 'full_snapshot',
    window_size INTEGER NOT NULL DEFAULT 1,
    no_update_action TEXT NOT NULL DEFAULT 'require_manifest',
    structure_change_action TEXT NOT NULL DEFAULT 'source_native_preview',
    text_update_action TEXT NOT NULL DEFAULT 'source_then_template',
    source_report_id INTEGER,
    source_table_id INTEGER,
    policy_source TEXT NOT NULL DEFAULT 'inferred',
    learned_from_report_id INTEGER,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_report_id) REFERENCES annual_reports(id) ON DELETE SET NULL,
    FOREIGN KEY (source_table_id) REFERENCES stat_tables(id) ON DELETE SET NULL,
    FOREIGN KEY (learned_from_report_id) REFERENCES annual_reports(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS yearbook_edition_manifest (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edition_year INTEGER NOT NULL,
    table_code TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL DEFAULT 'updated',
    target_period TEXT NOT NULL DEFAULT '',
    source_dataset_id INTEGER,
    title TEXT NOT NULL DEFAULT '',
    table_order INTEGER NOT NULL DEFAULT 0,
    unit TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    is_inferred INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_dataset_id) REFERENCES statistical_datasets(id) ON DELETE SET NULL,
    UNIQUE (edition_year, table_code)
);

CREATE INDEX IF NOT EXISTS idx_yearbook_edition_manifest_year
ON yearbook_edition_manifest(edition_year, lifecycle_status, table_order, table_code);

CREATE TABLE IF NOT EXISTS yearbook_reproduction_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    baseline_report_id INTEGER NOT NULL,
    report_year INTEGER NOT NULL,
    target_data_year INTEGER NOT NULL,
    source_snapshot_id INTEGER,
    status TEXT NOT NULL DEFAULT 'running',
    summary_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY (baseline_report_id) REFERENCES annual_reports(id) ON DELETE CASCADE,
    FOREIGN KEY (source_snapshot_id)
        REFERENCES source_data_snapshots(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_yearbook_reproduction_runs_report
ON yearbook_reproduction_runs(baseline_report_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS yearbook_reproduction_table_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    baseline_table_id INTEGER NOT NULL,
    recipe_id INTEGER,
    source_dataset_id INTEGER,
    status TEXT NOT NULL,
    compared_cell_count INTEGER NOT NULL DEFAULT 0,
    mismatch_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES yearbook_reproduction_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (baseline_table_id) REFERENCES stat_tables(id) ON DELETE CASCADE,
    FOREIGN KEY (recipe_id) REFERENCES yearbook_table_recipes(id) ON DELETE SET NULL,
    FOREIGN KEY (source_dataset_id) REFERENCES statistical_datasets(id) ON DELETE SET NULL,
    UNIQUE (run_id, baseline_table_id)
);

CREATE INDEX IF NOT EXISTS idx_yearbook_reproduction_results_run
ON yearbook_reproduction_table_results(run_id, status, baseline_table_id);

CREATE TABLE IF NOT EXISTS yearbook_reproduction_cell_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_result_id INTEGER NOT NULL,
    row_index INTEGER NOT NULL,
    col_index INTEGER NOT NULL,
    expected_value TEXT NOT NULL DEFAULT '',
    generated_value TEXT NOT NULL DEFAULT '',
    is_match INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (table_result_id)
        REFERENCES yearbook_reproduction_table_results(id) ON DELETE CASCADE,
    UNIQUE (table_result_id, row_index, col_index)
);

CREATE INDEX IF NOT EXISTS idx_yearbook_reproduction_cells_result
ON yearbook_reproduction_cell_results(table_result_id, is_match, row_index, col_index);

CREATE TABLE IF NOT EXISTS validation_rule_definitions (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    default_status TEXT NOT NULL,
    default_severity TEXT NOT NULL,
    owner_role TEXT NOT NULL,
    description TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS validation_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_code TEXT NOT NULL,
    table_title TEXT NOT NULL DEFAULT '',
    source_report_id INTEGER,
    structure_signature TEXT NOT NULL,
    table_type TEXT NOT NULL DEFAULT 'general',
    status TEXT NOT NULL DEFAULT 'draft',
    source TEXT NOT NULL DEFAULT 'heuristic',
    llm_model TEXT,
    rules_json TEXT NOT NULL DEFAULT '{}',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    approved_at TEXT,
    approved_by TEXT,
    FOREIGN KEY (source_report_id) REFERENCES annual_reports(id) ON DELETE SET NULL,
    UNIQUE (table_code, structure_signature)
);

CREATE INDEX IF NOT EXISTS idx_validation_profiles_code_latest
ON validation_profiles(table_code, updated_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_validation_profiles_source_report
ON validation_profiles(source_report_id);

CREATE TABLE IF NOT EXISTS validation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    rules_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    issue_count INTEGER NOT NULL DEFAULT 0,
    scope_kind TEXT NOT NULL DEFAULT 'full',
    base_run_id INTEGER,
    selected_rules_json TEXT NOT NULL DEFAULT '[]',
    reused_report_count INTEGER NOT NULL DEFAULT 0,
    reused_table_count INTEGER NOT NULL DEFAULT 0,
    reused_check_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (report_id) REFERENCES annual_reports(id) ON DELETE CASCADE,
    FOREIGN KEY (base_run_id) REFERENCES validation_runs(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_validation_runs_report_latest
ON validation_runs(report_id, completed_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS report_processing_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER,
    run_id INTEGER,
    source_file_name TEXT NOT NULL,
    source_file_path TEXT NOT NULL,
    source_storage TEXT NOT NULL DEFAULT 'local',
    source_object_key TEXT NOT NULL DEFAULT '',
    source_file_hash TEXT NOT NULL DEFAULT '',
    source_file_size INTEGER NOT NULL DEFAULT 0,
    source_type TEXT NOT NULL,
    report_year INTEGER NOT NULL,
    report_title TEXT NOT NULL,
    options_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    current_stage TEXT NOT NULL DEFAULT 'queued',
    progress_percent INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT NOT NULL DEFAULT '',
    lease_expires_at TEXT,
    last_heartbeat_at TEXT,
    error_message TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (report_id) REFERENCES annual_reports(id) ON DELETE SET NULL,
    FOREIGN KEY (run_id) REFERENCES validation_runs(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_report_processing_jobs_status
ON report_processing_jobs(status, updated_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_report_processing_jobs_report
ON report_processing_jobs(report_id);

CREATE TABLE IF NOT EXISTS report_processing_stages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    stage_name TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'running',
    result_json TEXT NOT NULL DEFAULT '{}',
    error_message TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY (job_id) REFERENCES report_processing_jobs(id) ON DELETE CASCADE,
    UNIQUE (job_id, stage_name, attempt)
);

CREATE INDEX IF NOT EXISTS idx_report_processing_stages_job
ON report_processing_stages(job_id, id);

CREATE TABLE IF NOT EXISTS validation_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    table_id INTEGER NOT NULL,
    profile_id INTEGER,
    rule_id TEXT NOT NULL,
    check_type TEXT NOT NULL,
    check_label TEXT NOT NULL,
    location TEXT NOT NULL,
    row_index INTEGER,
    col_index INTEGER,
    current_value TEXT NOT NULL DEFAULT '',
    expected_value TEXT,
    difference TEXT,
    status TEXT NOT NULL DEFAULT '정상',
    severity TEXT NOT NULL DEFAULT 'info',
    detail TEXT NOT NULL,
    formula TEXT,
    confidence REAL,
    FOREIGN KEY (run_id) REFERENCES validation_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (table_id) REFERENCES stat_tables(id) ON DELETE CASCADE,
    FOREIGN KEY (profile_id) REFERENCES validation_profiles(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_validation_checks_run_table
ON validation_checks(run_id, table_id);

CREATE TABLE IF NOT EXISTS translation_glossary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin_key TEXT NOT NULL UNIQUE,
    source_text TEXT NOT NULL,
    source_normalized TEXT NOT NULL,
    target_text TEXT NOT NULL,
    target_normalized TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    subcategory TEXT NOT NULL DEFAULT '',
    source_kind TEXT NOT NULL DEFAULT 'yearbook',
    source_report_id INTEGER,
    source_table_id INTEGER,
    status TEXT NOT NULL DEFAULT 'reference',
    approval_status TEXT NOT NULL DEFAULT 'unreviewed',
    approved_by TEXT NOT NULL DEFAULT '',
    glossary_version INTEGER NOT NULL DEFAULT 1,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    priority INTEGER NOT NULL DEFAULT 0,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    evidence TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    source_title TEXT NOT NULL DEFAULT '',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    valid_from TEXT NOT NULL DEFAULT '',
    valid_to TEXT NOT NULL DEFAULT '',
    verified_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_report_id) REFERENCES annual_reports(id) ON DELETE SET NULL,
    FOREIGN KEY (source_table_id) REFERENCES stat_tables(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_translation_glossary_source
ON translation_glossary(source_normalized, status, priority DESC);

CREATE TABLE IF NOT EXISTS translation_glossary_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    glossary_id INTEGER NOT NULL,
    alias_text TEXT NOT NULL,
    alias_normalized TEXT NOT NULL,
    alias_kind TEXT NOT NULL DEFAULT 'alias',
    FOREIGN KEY (glossary_id) REFERENCES translation_glossary(id) ON DELETE CASCADE,
    UNIQUE (glossary_id, alias_normalized)
);

CREATE INDEX IF NOT EXISTS idx_translation_glossary_alias
ON translation_glossary_aliases(alias_normalized, glossary_id);

CREATE TABLE IF NOT EXISTS glossary_audit_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_normalized TEXT NOT NULL,
    target_normalized TEXT NOT NULL,
    source_text TEXT NOT NULL,
    target_text TEXT NOT NULL,
    audit_status TEXT NOT NULL,
    spelling_status TEXT NOT NULL,
    translation_status TEXT NOT NULL,
    replacement_text TEXT NOT NULL DEFAULT '',
    difference TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    audited_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (source_normalized, target_normalized, model, prompt_version)
);

CREATE INDEX IF NOT EXISTS idx_glossary_audit_pair
ON glossary_audit_results(source_normalized, target_normalized, audit_status);

CREATE TABLE IF NOT EXISTS linguistic_review_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    table_id INTEGER NOT NULL,
    review_type TEXT NOT NULL,
    candidate_kind TEXT NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'document',
    location TEXT NOT NULL,
    row_index INTEGER,
    col_index INTEGER,
    current_value TEXT NOT NULL,
    korean_text TEXT NOT NULL DEFAULT '',
    english_text TEXT NOT NULL DEFAULT '',
    glossary_json TEXT NOT NULL DEFAULT '[]',
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    prompt_version TEXT NOT NULL DEFAULT '',
    reviewed_model TEXT NOT NULL DEFAULT '',
    review_result_json TEXT NOT NULL DEFAULT '',
    review_fingerprint TEXT NOT NULL DEFAULT '',
    resolution_source TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TEXT,
    FOREIGN KEY (run_id) REFERENCES validation_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (table_id) REFERENCES stat_tables(id) ON DELETE CASCADE,
    UNIQUE (run_id, table_id, review_type, location, current_value)
);

CREATE INDEX IF NOT EXISTS idx_linguistic_candidates_pending
ON linguistic_review_candidates(run_id, status, review_type, table_id);

CREATE TABLE IF NOT EXISTS linguistic_review_cache (
    fingerprint TEXT PRIMARY KEY,
    review_type TEXT NOT NULL,
    current_value TEXT NOT NULL,
    context_signature TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    reviewed_model TEXT NOT NULL,
    glossary_fingerprint TEXT NOT NULL DEFAULT '',
    decision_json TEXT NOT NULL,
    use_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_linguistic_review_cache_lookup
ON linguistic_review_cache(review_type, prompt_version, reviewed_model);

CREATE TABLE IF NOT EXISTS llm_usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    request_kind TEXT NOT NULL DEFAULT 'language_review',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    response_status TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES validation_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_events_run
ON llm_usage_events(run_id, created_at);

CREATE TABLE IF NOT EXISTS report_llm_assistance_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id INTEGER NOT NULL,
    workflow_kind TEXT NOT NULL,
    target_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    confidence REAL NOT NULL DEFAULT 0,
    model TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    plan_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (report_id) REFERENCES annual_reports(id) ON DELETE CASCADE,
    UNIQUE (report_id, workflow_kind, target_key)
);

CREATE INDEX IF NOT EXISTS idx_report_llm_assistance_report
ON report_llm_assistance_decisions(report_id, workflow_kind, status);
"""


def create_schema(connection: DatabaseConnection) -> None:
    connection.executescript(SCHEMA_SQL)


def ensure_schema_columns(connection: DatabaseConnection) -> None:
    ensure_column(connection, "stat_table_cells", "footnote_marker", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "stat_table_cells", "source_coordinate", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "stat_table_cells", "text_color", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "stat_table_cells", "parse_warnings_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(connection, "stat_tables", "parse_warnings_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(connection, "stat_tables", "source_department", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "stat_tables", "source_officer", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "stat_tables", "source_extension", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "stat_tables", "source_reference", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "stat_tables", "manually_edited_at", "TEXT")
    ensure_column(connection, "stat_tables", "edited_after_run_id", "INTEGER")
    ensure_column(connection, "yearbook_edit_passwords", "is_initial", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "annual_reports", "parse_warnings_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(connection, "annual_reports", "is_archived", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "annual_reports", "is_template", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "annual_reports", "origin_kind", "TEXT NOT NULL DEFAULT 'uploaded'")
    ensure_column(connection, "annual_reports", "base_report_id", "INTEGER")
    ensure_column(connection, "annual_reports", "layout_report_id", "INTEGER")
    ensure_column(connection, "report_incremental_uploads", "matcher_version", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "report_incremental_table_mappings", "reason_code", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "report_incremental_table_mappings", "evidence_json", "TEXT NOT NULL DEFAULT '{}'")
    ensure_column(connection, "report_incremental_table_mappings", "candidates_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(connection, "report_incremental_table_mappings", "confirmed_by_user", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "yearbook_reproduction_runs", "source_snapshot_id", "INTEGER")
    ensure_column(connection, "source_snapshot_batches", "visible_through_year", "INTEGER")
    ensure_column(connection, "statistical_dataset_items", "is_deleted", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "statistical_dataset_item_revisions", "is_deleted", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "yearbook_table_update_policies", "policy_source", "TEXT NOT NULL DEFAULT 'inferred'")
    ensure_column(connection, "yearbook_table_update_policies", "learned_from_report_id", "INTEGER")
    ensure_column(connection, "validation_runs", "scope_kind", "TEXT NOT NULL DEFAULT 'full'")
    ensure_column(connection, "validation_runs", "base_run_id", "INTEGER")
    ensure_column(connection, "validation_runs", "selected_rules_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(connection, "validation_runs", "reused_report_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "validation_runs", "reused_table_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "validation_runs", "reused_check_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "statistical_datasets", "source_kind", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "statistical_datasets", "storage_table", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "statistical_datasets", "introduced_batch_id", "INTEGER")
    ensure_column(connection, "translation_glossary", "subcategory", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "translation_glossary", "source_url", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "translation_glossary", "source_title", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "translation_glossary", "aliases_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(connection, "translation_glossary", "valid_from", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "translation_glossary", "valid_to", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "translation_glossary", "verified_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "translation_glossary", "approval_status", "TEXT NOT NULL DEFAULT 'unreviewed'")
    ensure_column(connection, "translation_glossary", "approved_by", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "translation_glossary", "glossary_version", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(connection, "translation_glossary", "provenance_json", "TEXT NOT NULL DEFAULT '{}'")
    ensure_column(connection, "linguistic_review_candidates", "source_kind", "TEXT NOT NULL DEFAULT 'document'")
    ensure_column(connection, "linguistic_review_candidates", "prompt_version", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "linguistic_review_candidates", "reviewed_model", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "linguistic_review_candidates", "review_result_json", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "linguistic_review_candidates", "review_fingerprint", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "linguistic_review_candidates", "resolution_source", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "report_processing_jobs", "source_storage", "TEXT NOT NULL DEFAULT 'local'")
    ensure_column(connection, "report_processing_jobs", "source_object_key", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "report_processing_jobs", "source_file_hash", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "report_processing_jobs", "source_file_size", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "report_processing_jobs", "progress_percent", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "report_processing_jobs", "attempt_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(connection, "report_processing_jobs", "lease_owner", "TEXT NOT NULL DEFAULT ''")
    ensure_column(connection, "report_processing_jobs", "lease_expires_at", "TEXT")
    ensure_column(connection, "report_processing_jobs", "last_heartbeat_at", "TEXT")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_report_processing_jobs_source_hash
        ON report_processing_jobs(source_file_hash, report_year, report_title)
        """
    )
    backfill_source_snapshot_batch_visibility(connection)


def backfill_source_snapshot_batch_visibility(connection: DatabaseConnection) -> None:
    """Give legacy snapshot memberships a safe historical period boundary."""

    connection.execute(
        """
        UPDATE source_snapshot_batches AS membership
        SET visible_through_year = CASE
            WHEN (
                SELECT batch.import_kind
                FROM series_import_batches AS batch
                WHERE batch.id = membership.source_batch_id
            ) = 'relational_incremental' THEN (
                SELECT batch.target_year - 1
                FROM series_import_batches AS batch
                WHERE batch.id = membership.source_batch_id
            )
            ELSE (
                SELECT MIN(snapshot.target_year)
                FROM source_snapshot_batches AS related_membership
                JOIN source_data_snapshots AS snapshot
                  ON snapshot.id = related_membership.snapshot_id
                WHERE related_membership.source_batch_id = membership.source_batch_id
            )
        END
        WHERE visible_through_year IS NULL
        """
    )


def classify_glossary_approval_metadata(connection: DatabaseConnection) -> None:
    """Backfill explicit approval metadata from the legacy source/status fields."""

    connection.execute(
        """
        UPDATE translation_glossary
        SET approval_status = CASE
                WHEN source_kind = 'official' THEN 'approved'
                WHEN source_kind IN ('curated', 'seed') THEN 'reference'
                WHEN status IN ('llm_verified', 'llm_reviewed') THEN 'model_reviewed'
                WHEN status IN ('rejected', 'quarantined') THEN 'rejected'
                ELSE 'reference'
            END,
            approved_by = CASE
                WHEN source_kind = 'official' THEN 'official_source'
                WHEN source_kind = 'curated' THEN 'curator'
                WHEN source_kind = 'seed' THEN 'project_seed'
                WHEN status IN ('llm_verified', 'llm_reviewed') THEN 'llm'
                ELSE approved_by
            END,
            glossary_version = CASE
                WHEN glossary_version < 1 THEN 1
                ELSE glossary_version
            END
        WHERE approval_status = 'unreviewed' OR glossary_version < 1
        """
    )


def classify_linguistic_candidate_sources(connection: DatabaseConnection) -> None:
    """Make blue-marked HWPX candidates explicit without changing their UI type."""

    connection.execute(
        """
        UPDATE linguistic_review_candidates
        SET source_kind = CASE
                WHEN candidate_kind LIKE 'blue_text%' THEN 'blue'
                ELSE 'document'
            END
        WHERE source_kind = 'document' OR source_kind = ''
        """
    )


def init_db(connection: DatabaseConnection) -> None:
    """Compatibility entry point; migrations are coordinated in db.migrations."""

    from app.db.migrations import ensure_database_ready

    ensure_database_ready(connection)


def ensure_column(
    connection: DatabaseConnection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    if is_postgres_connection(connection):
        columns = {
            row["name"]
            for row in connection.execute(
                """
                SELECT column_name AS name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = ?
                """,
                (table_name,),
            )
        }
    else:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})")}
    if column_name in columns:
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def is_postgres_connection(connection: object) -> bool:
    return bool(getattr(connection, "is_postgres", False))


def detach_report_lineage_on_delete(connection: DatabaseConnection) -> None:
    """Keep derived report records when their selected base report is removed."""

    if is_postgres_connection(connection):
        connection.execute("ALTER TABLE report_update_batches ALTER COLUMN base_report_id DROP NOT NULL")
        connection.execute(
            "ALTER TABLE report_update_batches DROP CONSTRAINT IF EXISTS report_update_batches_base_report_id_fkey"
        )
        connection.execute(
            """
            ALTER TABLE report_update_batches
            ADD CONSTRAINT report_update_batches_base_report_id_fkey
            FOREIGN KEY (base_report_id) REFERENCES annual_reports(id) ON DELETE SET NULL
            """
        )
        connection.execute("ALTER TABLE report_incremental_uploads ALTER COLUMN base_report_id DROP NOT NULL")
        connection.execute(
            "ALTER TABLE report_incremental_uploads DROP CONSTRAINT IF EXISTS report_incremental_uploads_base_report_id_fkey"
        )
        connection.execute(
            """
            ALTER TABLE report_incremental_uploads
            ADD CONSTRAINT report_incremental_uploads_base_report_id_fkey
            FOREIGN KEY (base_report_id) REFERENCES annual_reports(id) ON DELETE SET NULL
            """
        )
        return

    if _sqlite_needs_nullable_set_null_base_fk(connection, "report_update_batches"):
        _rebuild_report_update_batches_for_detached_base(connection)
    if _sqlite_needs_nullable_set_null_base_fk(connection, "report_incremental_uploads"):
        _rebuild_report_incremental_uploads_for_detached_base(connection)


def _sqlite_needs_nullable_set_null_base_fk(connection: DatabaseConnection, table_name: str) -> bool:
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is None:
        return False

    columns = {str(row["name"]): row for row in connection.execute(f"PRAGMA table_info({table_name})")}
    base_column = columns.get("base_report_id")
    if base_column is not None and int(base_column["notnull"] or 0):
        return True

    for row in connection.execute(f"PRAGMA foreign_key_list({table_name})"):
        if str(row["from"]) == "base_report_id" and str(row["table"]) == "annual_reports":
            return str(row["on_delete"]).upper() != "SET NULL"
    return True


def _rebuild_report_update_batches_for_detached_base(connection: DatabaseConnection) -> None:
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("DROP TABLE IF EXISTS report_update_batches_new")
    connection.execute(
        """
        CREATE TABLE report_update_batches_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_report_id INTEGER,
            report_id INTEGER NOT NULL,
            update_kind TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'completed',
            changed_table_count INTEGER NOT NULL DEFAULT 0,
            unchanged_table_count INTEGER NOT NULL DEFAULT 0,
            added_table_count INTEGER NOT NULL DEFAULT 0,
            deleted_table_count INTEGER NOT NULL DEFAULT 0,
            changed_cell_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (base_report_id) REFERENCES annual_reports(id) ON DELETE SET NULL,
            FOREIGN KEY (report_id) REFERENCES annual_reports(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        INSERT INTO report_update_batches_new (
            id, base_report_id, report_id, update_kind, status,
            changed_table_count, unchanged_table_count, added_table_count,
            deleted_table_count, changed_cell_count, created_at
        )
        SELECT
            id, base_report_id, report_id, update_kind, status,
            changed_table_count, unchanged_table_count, added_table_count,
            deleted_table_count, changed_cell_count, created_at
        FROM report_update_batches
        """
    )
    connection.execute("DROP TABLE report_update_batches")
    connection.execute("ALTER TABLE report_update_batches_new RENAME TO report_update_batches")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_report_update_batches_report
        ON report_update_batches(report_id, created_at DESC, id DESC)
        """
    )
    connection.execute("PRAGMA foreign_keys = ON")


def _rebuild_report_incremental_uploads_for_detached_base(connection: DatabaseConnection) -> None:
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("DROP TABLE IF EXISTS report_incremental_uploads_new")
    connection.execute(
        """
        CREATE TABLE report_incremental_uploads_new (
            report_id INTEGER PRIMARY KEY,
            base_report_id INTEGER,
            target_year INTEGER NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            source_hash TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (report_id) REFERENCES annual_reports(id) ON DELETE CASCADE,
            FOREIGN KEY (base_report_id) REFERENCES annual_reports(id) ON DELETE SET NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO report_incremental_uploads_new (
            report_id, base_report_id, target_year, payload_json, source_hash, created_at
        )
        SELECT report_id, base_report_id, target_year, payload_json, source_hash, created_at
        FROM report_incremental_uploads
        """
    )
    connection.execute("DROP TABLE report_incremental_uploads")
    connection.execute("ALTER TABLE report_incremental_uploads_new RENAME TO report_incremental_uploads")
    connection.execute("PRAGMA foreign_keys = ON")


def canonicalize_validation_results(connection: DatabaseConnection) -> None:
    """Archive the former write table and expose a read-only compatibility view."""

    if getattr(connection, "is_postgres", False):
        table_rows = connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name IN ('validation_issues', 'validation_issues_legacy')
            """
        ).fetchall()
        table_names = {str(row["table_name"]) for row in table_rows}
        view_row = connection.execute(
            """
            SELECT 1
            FROM information_schema.views
            WHERE table_schema = current_schema() AND table_name = 'validation_issues'
            """
        ).fetchone()
    else:
        table_rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name IN ('validation_issues', 'validation_issues_legacy')
            """
        ).fetchall()
        table_names = {str(row["name"]) for row in table_rows}
        view_row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'view' AND name = 'validation_issues'"
        ).fetchone()

    if "validation_issues" in table_names and "validation_issues_legacy" not in table_names:
        connection.execute(
            "ALTER TABLE validation_issues RENAME TO validation_issues_legacy"
        )
        table_names.remove("validation_issues")
        table_names.add("validation_issues_legacy")

    if "validation_issues" not in table_names and view_row is None:
        connection.execute(
            """
            CREATE VIEW validation_issues AS
            SELECT
                id,
                run_id,
                table_id,
                rule_id,
                check_type AS issue_type,
                location,
                row_index,
                col_index,
                current_value,
                expected_value,
                difference,
                status,
                severity,
                detail,
                formula
            FROM validation_checks
            WHERE status <> '정상'
            """
        )

    connection.execute(
        """
        UPDATE validation_runs
        SET issue_count = (
            SELECT COUNT(*)
            FROM validation_checks
            WHERE validation_checks.run_id = validation_runs.id
              AND validation_checks.status <> '정상'
        )
        """
    )


def restore_semantic_type_qualifiers(connection: DatabaseConnection) -> None:
    """Restore Type A/B header qualifiers removed by an older cell normalizer."""

    qualifier_by_column = {2: "[Type A]", 3: "[Type B]"}
    for col_index, qualifier in qualifier_by_column.items():
        header_text = (
            "출자기관\nGovernment-funded Organizations"
            if col_index == 2
            else "출연기관\nGovernment-funded Organizations"
        )
        connection.execute(
            """
            UPDATE stat_table_cells
            SET text_value = text_value || char(10) || ?
            WHERE row_index = 0
              AND col_index = ?
              AND text_value = ?
              AND table_id IN (
                  SELECT id
                  FROM stat_tables
                  WHERE code = '5-1-10'
              )
            """,
            (qualifier, col_index, header_text),
        )


def retire_terminology_validation(connection: DatabaseConnection) -> None:
    """Remove the retired terminology-suggestion category and its stored output."""

    connection.execute("DELETE FROM linguistic_review_cache WHERE review_type = '용어 제안'")
    connection.execute("DELETE FROM linguistic_review_candidates WHERE review_type = '용어 제안'")
    connection.execute(
        "DELETE FROM validation_checks WHERE check_type = '용어 제안' OR rule_id = 'llm.terminology_review'"
    )
    connection.execute("DELETE FROM validation_rule_definitions WHERE key = 'terminology'")

    for row in connection.execute("SELECT id, rules_json FROM validation_profiles").fetchall():
        try:
            rules = json.loads(str(row["rules_json"] or "{}"))
        except json.JSONDecodeError:
            continue
        changed = False
        for key in ("common_rules",):
            values = rules.get(key)
            if isinstance(values, list) and "terminology" in values:
                rules[key] = [value for value in values if value != "terminology"]
                changed = True
        for key in ("rule_definitions", "checks", "table_rules"):
            values = rules.get(key)
            if not isinstance(values, list):
                continue
            filtered = [
                value
                for value in values
                if not (
                    isinstance(value, dict)
                    and (
                        value.get("key") == "terminology"
                        or value.get("check_group") == "terminology"
                        or value.get("check_type") == "용어 제안"
                    )
                )
            ]
            if len(filtered) != len(values):
                rules[key] = filtered
                changed = True
        if changed:
            connection.execute(
                "UPDATE validation_profiles SET rules_json = ? WHERE id = ?",
                (json.dumps(rules, ensure_ascii=False), int(row["id"])),
            )

    connection.execute(
        """
        UPDATE validation_runs
        SET issue_count = (
            SELECT COUNT(*)
            FROM validation_checks
            WHERE validation_checks.run_id = validation_runs.id
              AND validation_checks.status <> '정상'
        )
        """
    )


def retire_metadata_validation(connection: DatabaseConnection) -> None:
    """Historical cleanup retained so older databases migrate deterministically."""

    retired_rule_filter = "rule_id = 'metadata.required' OR rule_id LIKE '%.metadata_required'"
    connection.execute(
        f"DELETE FROM validation_checks WHERE check_type = '메타정보 검수' OR {retired_rule_filter}"
    )
    retire_metadata_linguistic_reviews(connection)
    connection.execute(
        """
        UPDATE validation_runs
        SET issue_count = (
            SELECT COUNT(*) FROM validation_checks
            WHERE validation_checks.run_id = validation_runs.id
              AND validation_checks.status <> '정상'
        )
        """
    )

    profile_rows = connection.execute(
        """
        SELECT id, rules_json
        FROM validation_profiles
        WHERE rules_json LIKE '%metadata_required%'
           OR rules_json LIKE '%unit_required%'
           OR rules_json LIKE '%\"metadata\"%'
        """
    ).fetchall()
    for row in profile_rows:
        try:
            rules = json.loads(str(row["rules_json"] or "{}"))
        except json.JSONDecodeError:
            continue
        if not isinstance(rules, dict):
            continue
        rules["common_rules"] = [
            key for key in rules.get("common_rules", []) if key != "metadata"
        ]
        rules["rule_definitions"] = [
            definition
            for definition in rules.get("rule_definitions", [])
            if not isinstance(definition, dict) or definition.get("key") != "metadata"
        ]
        for field in ("checks", "table_rules"):
            rules[field] = [
                spec
                for spec in rules.get(field, [])
                if not isinstance(spec, dict)
                or spec.get("type") not in {"unit_required", "metadata_required"}
            ]
        connection.execute(
            "UPDATE validation_profiles SET rules_json = ? WHERE id = ?",
            (json.dumps(rules, ensure_ascii=False), int(row["id"])),
        )


def restore_metadata_validation(connection: DatabaseConnection) -> None:
    """Restore presence checks while keeping metadata out of language review."""

    retire_metadata_linguistic_reviews(connection)
    retire_stale_linguistic_review_records(connection)
    restore_metadata_profile_specs(connection)
    restore_latest_run_metadata_checks(connection)


def restore_metadata_profile_specs(connection: DatabaseConnection) -> None:
    metadata_definition = next(
        definition.to_dict()
        for definition in REQUIRED_RULE_DEFINITIONS
        if definition.key == "metadata"
    )
    profile_rows = connection.execute(
        """
        SELECT vp.id, vp.table_code, vp.source_report_id, vp.rules_json,
               COALESCE((
                   SELECT st.unit
                   FROM stat_tables st
                   WHERE st.report_id = vp.source_report_id AND st.code = vp.table_code
                   ORDER BY st.id
                   LIMIT 1
               ), '') AS current_unit
        FROM validation_profiles vp
        """
    ).fetchall()
    for row in profile_rows:
        try:
            rules = json.loads(str(row["rules_json"] or "{}"))
        except json.JSONDecodeError:
            continue
        if not isinstance(rules, dict):
            continue

        common_rules = [
            key for key in rules.get("common_rules", []) if key != "metadata"
        ]
        rules["common_rules"] = [*common_rules, "metadata"]
        rule_definitions = [
            definition
            for definition in rules.get("rule_definitions", [])
            if not isinstance(definition, dict) or definition.get("key") != "metadata"
        ]
        rules["rule_definitions"] = [*rule_definitions, metadata_definition]

        metadata_spec = metadata_profile_spec(
            str(row["table_code"]),
            str(row["current_unit"] or ""),
        )
        checks = [
            spec
            for spec in rules.get("checks", [])
            if not isinstance(spec, dict)
            or spec.get("type") not in {"unit_required", "metadata_required"}
        ]
        rules["checks"] = [metadata_spec, *checks]
        rules["table_rules"] = [
            spec
            for spec in rules.get("table_rules", [])
            if not isinstance(spec, dict)
            or spec.get("type") not in {"unit_required", "metadata_required"}
        ]
        connection.execute(
            "UPDATE validation_profiles SET rules_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(rules, ensure_ascii=False), int(row["id"])),
        )


def metadata_profile_spec(table_code: str, expected_unit: str) -> dict[str, object]:
    return {
        "id": f"profile.{table_code}.metadata_required",
        "type": "metadata_required",
        "category": "common",
        "check_group": "metadata",
        "check_type": "메타정보 검수",
        "failure_status": "확인 필요",
        "severity": "warning",
        "label": "단위·기준일·출처 메타정보 확인",
        "fields": ["unit", "base_date", "source"],
        "expected_unit": expected_unit,
        "confidence": 1.0,
    }


def restore_latest_run_metadata_checks(connection: DatabaseConnection) -> None:
    latest_runs = connection.execute(
        """
        SELECT vr.id, vr.report_id
        FROM validation_runs vr
        JOIN (
            SELECT report_id, MAX(id) AS run_id
            FROM validation_runs
            GROUP BY report_id
        ) latest ON latest.run_id = vr.id
        """
    ).fetchall()
    for run in latest_runs:
        run_id = int(run["id"])
        report_id = int(run["report_id"])
        connection.execute(
            "DELETE FROM validation_checks WHERE run_id = ? AND check_type = '메타정보 검수'",
            (run_id,),
        )
        table_rows = connection.execute(
            """
            SELECT st.id, st.code, st.unit, st.base_date, st.source, vp.id AS profile_id
            FROM stat_tables st
            LEFT JOIN validation_profiles vp
              ON vp.source_report_id = st.report_id AND vp.table_code = st.code
            WHERE st.report_id = ?
            ORDER BY st.table_order, st.id
            """,
            (report_id,),
        ).fetchall()
        for table in table_rows:
            metadata = (
                ("단위", str(table["unit"] or "").strip()),
                ("기준일", str(table["base_date"] or "").strip()),
                ("출처", str(table["source"] or "").strip()),
            )
            missing = [label for label, value in metadata if not value]
            current_value = " | ".join(
                f"{label}: {value or '없음'}" for label, value in metadata
            )
            difference = f"누락: {', '.join(missing)}" if missing else None
            status = "확인 필요" if missing else "정상"
            severity = "warning" if missing else "info"
            detail = (
                f"출처·메타정보 탭에서 {', '.join(missing)} 항목이 누락되어 있습니다."
                if missing
                else "출처·메타정보 탭의 단위, 기준일, 출처가 모두 입력되어 있습니다."
            )
            rule_id = f"profile.{table['code']}.metadata_required"
            connection.execute(
                """
                INSERT INTO validation_checks (
                    run_id, table_id, profile_id, rule_id, check_type, check_label,
                    location, current_value, expected_value, difference, status,
                    severity, detail, confidence
                ) VALUES (?, ?, ?, ?, '메타정보 검수', '단위·기준일·출처 메타정보 확인',
                          '출처·메타정보', ?, '단위·기준일·출처 입력', ?, ?, ?, ?, 1.0)
                """,
                (
                    run_id,
                    int(table["id"]),
                    int(table["profile_id"]) if table["profile_id"] is not None else None,
                    rule_id,
                    current_value,
                    difference,
                    status,
                    severity,
                    detail,
                ),
            )
    connection.execute(
        """
        UPDATE validation_runs
        SET issue_count = (
            SELECT COUNT(*) FROM validation_checks
            WHERE validation_checks.run_id = validation_runs.id
              AND validation_checks.status <> '정상'
        )
        """
    )


def repair_misaligned_linguistic_reviews(connection: DatabaseConnection) -> None:
    """Reset LLM results whose returned source text belongs to another candidate."""

    rows = connection.execute(
        """
        SELECT id, run_id, table_id, review_type, candidate_kind, location,
               row_index, col_index, current_value, review_result_json,
               review_fingerprint
        FROM linguistic_review_candidates
        WHERE status = 'reviewed'
          AND resolution_source = 'llm'
          AND review_result_json <> ''
        """
    ).fetchall()
    materialized_values: dict[tuple[object, ...], list[str]] = {}
    for record in connection.execute(
        """
        SELECT run_id, table_id, rule_id, location, row_index, col_index, current_value
        FROM validation_checks
        WHERE rule_id IN (
            'llm.spelling_review', 'llm.terminology_review',
            'llm.translation_review', 'source.blue_text_review'
        )
        """
    ):
        key = (
            int(record["run_id"]),
            int(record["table_id"]),
            str(record["rule_id"]),
            str(record["location"]),
            record["row_index"],
            record["col_index"],
        )
        materialized_values.setdefault(key, []).append(str(record["current_value"] or ""))

    invalid_rows_by_id: dict[int, Any] = {}
    for row in rows:
        try:
            decision = json.loads(str(row["review_result_json"] or "{}"))
        except json.JSONDecodeError:
            invalid_rows_by_id[int(row["id"])] = row
            continue
        returned_value = decision.get("current_value", "") if isinstance(decision, dict) else ""
        if canonical_review_text(str(returned_value)) != canonical_review_text(str(row["current_value"])):
            invalid_rows_by_id[int(row["id"])] = row
            continue

        rule_id = linguistic_materialized_rule_id(
            str(row["candidate_kind"] or ""),
            str(row["review_type"] or ""),
        )
        record_key = (
            int(row["run_id"]),
            int(row["table_id"]),
            rule_id,
            str(row["location"]),
            row["row_index"],
            row["col_index"],
        )
        if any(
            canonical_review_text(value)
            != canonical_review_text(str(row["current_value"]))
            for value in materialized_values.get(record_key, [])
        ):
            invalid_rows_by_id[int(row["id"])] = row

    invalid_rows = list(invalid_rows_by_id.values())

    stale_fingerprints = {
        str(row["review_fingerprint"])
        for row in invalid_rows
        if str(row["review_fingerprint"] or "")
    }
    if stale_fingerprints:
        connection.executemany(
            "DELETE FROM linguistic_review_cache WHERE fingerprint = ?",
            [(fingerprint,) for fingerprint in stale_fingerprints],
        )

    record_keys: set[tuple[object, ...]] = set()
    invalid_translation_sources: set[tuple[int, str]] = set()
    for row in invalid_rows:
        candidate_kind = str(row["candidate_kind"] or "")
        review_type = str(row["review_type"] or "")
        rule_id = linguistic_materialized_rule_id(candidate_kind, review_type)
        if rule_id:
            record_keys.add(
                (
                    int(row["run_id"]),
                    int(row["table_id"]),
                    rule_id,
                    str(row["location"]),
                    row["row_index"],
                    row["col_index"],
                )
            )
        if review_type == "번역 검수" and not candidate_kind.startswith("blue_text"):
            invalid_translation_sources.add(
                (int(row["table_id"]), canonical_review_text(str(row["current_value"])))
            )

    if record_keys:
        delete_sql = """
            DELETE FROM {table_name}
            WHERE run_id = ? AND table_id = ? AND rule_id = ? AND location = ?
              AND row_index IS NOT DISTINCT FROM ?
              AND col_index IS NOT DISTINCT FROM ?
        """
        connection.executemany(
            delete_sql.format(table_name="validation_checks"),
            list(record_keys),
        )

    if invalid_rows:
        connection.executemany(
            """
            UPDATE linguistic_review_candidates
            SET status = 'pending', reviewed_at = NULL, reviewed_model = '',
                review_result_json = '', review_fingerprint = '', resolution_source = ''
            WHERE id = ?
            """,
            [(int(row["id"]),) for row in invalid_rows],
        )

    glossary_rows = connection.execute(
        """
        SELECT id, source_table_id, source_text, evidence
        FROM translation_glossary
        WHERE status = 'llm_reviewed' AND source_kind = 'llm'
        """
    ).fetchall()
    metadata_location_pattern = re.compile(r"\s(분야|단위|기준일|주석|출처)(?:[.(]|$)")
    stale_glossary_ids = {
        int(row["id"])
        for row in glossary_rows
        if (
            row["source_table_id"] is not None
            and (
                int(row["source_table_id"]),
                canonical_review_text(str(row["source_text"])),
            )
            in invalid_translation_sources
        )
        or metadata_location_pattern.search(str(row["evidence"] or "")) is not None
        or looks_like_note_payload(str(row["source_text"] or ""))
    }
    if stale_glossary_ids:
        connection.executemany(
            "DELETE FROM translation_glossary WHERE id = ?",
            [(glossary_id,) for glossary_id in stale_glossary_ids],
        )

    connection.execute(
        """
        UPDATE validation_runs
        SET issue_count = (
            SELECT COUNT(*) FROM validation_checks
            WHERE validation_checks.run_id = validation_runs.id
              AND validation_checks.status <> '정상'
        )
        """
    )


def linguistic_materialized_rule_id(candidate_kind: str, review_type: str) -> str:
    if candidate_kind.startswith("blue_text"):
        return "source.blue_text_review"
    return {
        "오탈자 검수": "llm.spelling_review",
        "용어 제안": "llm.terminology_review",
        "번역 검수": "llm.translation_review",
    }.get(review_type, "")


def retire_metadata_linguistic_reviews(connection: DatabaseConnection) -> None:
    locations = ("분야", "단위", "기준일", "주석", "출처")
    location_filter = " OR ".join("location = ? OR location LIKE ?" for _ in locations)
    location_params = tuple(
        value
        for location in locations
        for value in (location, f"{location} (%")
    )
    language_rule_ids = (
        "llm.spelling_review",
        "llm.terminology_review",
        "llm.translation_review",
    )
    rule_placeholders = ", ".join("?" for _ in language_rule_ids)

    connection.execute(
        f"""
        DELETE FROM linguistic_review_cache
        WHERE fingerprint IN (
            SELECT review_fingerprint
            FROM linguistic_review_candidates
            WHERE review_fingerprint <> '' AND ({location_filter})
        )
        """,
        location_params,
    )
    connection.execute(
        f"DELETE FROM linguistic_review_candidates WHERE {location_filter}",
        location_params,
    )
    connection.execute(
        f"""
        DELETE FROM validation_checks
        WHERE rule_id IN ({rule_placeholders}) AND ({location_filter})
        """,
        (*language_rule_ids, *location_params),
    )
    retire_mislinked_metadata_payload_reviews(connection, language_rule_ids)


def retire_mislinked_metadata_payload_reviews(
    connection: DatabaseConnection,
    language_rule_ids: tuple[str, ...],
) -> None:
    candidate_rows = connection.execute(
        """
        SELECT lrc.id, lrc.review_fingerprint, lrc.review_result_json, st.note, st.source
        FROM linguistic_review_candidates lrc
        JOIN stat_tables st ON st.id = lrc.table_id
        WHERE lrc.status = 'reviewed' AND lrc.review_result_json <> ''
        """
    ).fetchall()
    reset_candidate_ids: list[tuple[int]] = []
    stale_fingerprints: list[tuple[str]] = []
    for row in candidate_rows:
        try:
            decision = json.loads(str(row["review_result_json"] or "{}"))
        except json.JSONDecodeError:
            continue
        if not isinstance(decision, dict):
            continue
        if not any(
            matches_long_metadata_payload(value, str(row["note"] or ""), str(row["source"] or ""))
            for value in (
                decision.get("current_value", ""),
                decision.get("expected_value", ""),
            )
        ):
            continue
        reset_candidate_ids.append((int(row["id"]),))
        fingerprint = str(row["review_fingerprint"] or "")
        if fingerprint:
            stale_fingerprints.append((fingerprint,))

    if stale_fingerprints:
        connection.executemany(
            "DELETE FROM linguistic_review_cache WHERE fingerprint = ?",
            stale_fingerprints,
        )
    if reset_candidate_ids:
        connection.executemany(
            """
            UPDATE linguistic_review_candidates
            SET status = 'pending', reviewed_at = NULL, reviewed_model = '',
                review_result_json = '', review_fingerprint = '', resolution_source = ''
            WHERE id = ?
            """,
            reset_candidate_ids,
        )

    rule_placeholders = ", ".join("?" for _ in language_rule_ids)
    rows = connection.execute(
        f"""
        SELECT record.id, record.current_value, record.expected_value, st.note, st.source
        FROM validation_checks record
        JOIN stat_tables st ON st.id = record.table_id
        WHERE record.rule_id IN ({rule_placeholders})
        """,
        language_rule_ids,
    ).fetchall()
    record_ids = [
        (int(row["id"]),)
        for row in rows
        if matches_long_metadata_payload(
            str(row["current_value"] or ""),
            str(row["note"] or ""),
            str(row["source"] or ""),
        )
        or matches_long_metadata_payload(
            str(row["expected_value"] or ""),
            str(row["note"] or ""),
            str(row["source"] or ""),
        )
    ]
    if record_ids:
        connection.executemany("DELETE FROM validation_checks WHERE id = ?", record_ids)


def retire_stale_linguistic_review_records(connection: DatabaseConnection) -> None:
    """Remove language results that contain note/source payloads in cell locations."""

    language_rule_ids = (
        "llm.spelling_review",
        "llm.terminology_review",
        "llm.translation_review",
    )
    placeholders = ", ".join("?" for _ in language_rule_ids)
    rows = connection.execute(
        f"""
        SELECT record.id, record.current_value, record.expected_value,
               st.note, st.source
        FROM validation_checks record
        JOIN stat_tables st ON st.id = record.table_id
        WHERE record.rule_id IN ({placeholders})
        """,
        language_rule_ids,
    ).fetchall()
    stale_ids: list[tuple[int]] = []
    for row in rows:
        current_value = str(row["current_value"] or "")
        expected_value = str(row["expected_value"] or "")
        if matches_long_metadata_payload(
            current_value,
            str(row["note"] or ""),
            str(row["source"] or ""),
        ) or matches_long_metadata_payload(
            expected_value,
            str(row["note"] or ""),
            str(row["source"] or ""),
        ) or looks_like_note_payload(current_value):
            stale_ids.append((int(row["id"]),))

    if stale_ids:
        connection.executemany("DELETE FROM validation_checks WHERE id = ?", stale_ids)


def looks_like_note_payload(value: str) -> bool:
    stripped = str(value or "").strip()
    if stripped.startswith(("*", "\\*", "#주", "[출처:")):
        return True
    return bool(re.match(r"^주\s*\d+\)", stripped))


def canonical_review_text(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).lower()


def matches_long_metadata_payload(value: str, note: str, source: str) -> bool:
    normalized_value = canonical_review_text(value)
    if len(normalized_value) < 8:
        return False
    for metadata_value in (note, source):
        normalized_metadata = canonical_review_text(metadata_value)
        if len(normalized_metadata) < 8:
            continue
        if normalized_value in normalized_metadata or normalized_metadata in normalized_value:
            return True
    return False


def seed_validation_rule_definitions(connection: DatabaseConnection) -> None:
    connection.executemany(
        "DELETE FROM validation_rule_definitions WHERE key = ?",
        [("unit",), ("empty",), ("terminology",)],
    )
    connection.executemany(
        """
        INSERT INTO validation_rule_definitions (
            key, name, default_status, default_severity, owner_role, description
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            name = excluded.name,
            default_status = excluded.default_status,
            default_severity = excluded.default_severity,
            owner_role = excluded.owner_role,
            description = excluded.description,
            updated_at = CURRENT_TIMESTAMP
        """,
        [
            (
                definition.key,
                definition.name,
                definition.default_status,
                definition.default_severity,
                definition.owner_role,
                definition.description,
            )
            for definition in REQUIRED_RULE_DEFINITIONS
        ],
    )
