import { useEffect, useMemo } from "react";

import type {
  ReportOption,
  ReportSummary,
  StatTable,
  StatTableSummary,
  TableStatus,
  ValidationCatalogItem,
} from "../types";
import type { ValidationJob } from "../api/reportApi";
import { ReportSummaryPanel } from "./ReportSummaryPanel";
import { TableList } from "./TableList";
import { TablePreview } from "./TablePreview";
import {
  REVALIDATION_REQUIRED_FILTER,
  incrementalReviewType,
  type ReportReviewStage,
  summaryWithValidationVisibility,
} from "../utils/validationVisibility";

type FilterValue = TableStatus | "all" | "has_issues";

export function matchesWorkspaceFilter(
  table: StatTableSummary,
  query: string,
  filter: FilterValue,
  hiddenValidationTypes: ReadonlySet<string>,
  reviewStage: ReportReviewStage = "validated",
) {
  const normalizedQuery = query.trim().toLowerCase();
  const hasQueryMatch =
    !normalizedQuery ||
    [table.title, table.title_en, table.code]
      .join(" ")
      .toLowerCase()
      .includes(normalizedQuery);
  const hasFilterMatch =
    filter === "all" ||
    table.status === filter ||
    (filter === "has_issues" &&
      (table.status !== "normal" ||
        table.checks.some((check) => check.status !== "정상")));

  // `tables` arrives after the selected validation types have been applied.
  // A type choice is therefore a real table-list filter as well as a check
  // display filter: when only "비율 검수" is selected, retain only tables
  // that were actually ratio-checked, including tables whose result is normal.
  const generatedReviewType = incrementalReviewType(table);
  const hasSelectedValidationCheck =
    table.checks.length > 0 ||
    (table.validated_types ?? []).some((type) => !hiddenValidationTypes.has(type)) ||
    Boolean(generatedReviewType && !hiddenValidationTypes.has(generatedReviewType)) ||
    Boolean(table.validation_stale && !hiddenValidationTypes.has(REVALIDATION_REQUIRED_FILTER));

  // Before the first validation run there is no validation evidence to use as
  // a population filter. Keep every table visible; draft diagnostics are
  // expressed through their generated review status instead.
  const belongsToReviewScope =
    reviewStage === "validated"
      ? hasSelectedValidationCheck
      : reviewStage === "draft"
        ? !generatedReviewType || !hiddenValidationTypes.has(generatedReviewType)
        : true;

  return hasQueryMatch && belongsToReviewScope && hasFilterMatch;
}

interface ReportWorkspaceProps {
  datasetLabel: string;
  summary: ReportSummary;
  reviewStage: ReportReviewStage;
  availableReports: ReportOption[];
  tables: StatTableSummary[];
  selectedTableId: string;
  selectedReportId: string;
  selectedTableDetail?: StatTable | null;
  query: string;
  filter: FilterValue;
  validationTypes: string[];
  disabledValidationTypes: ReadonlySet<string>;
  validationCatalog: ValidationCatalogItem[];
  hiddenValidationTypes: ReadonlySet<string>;
  validationRunState: "idle" | "running" | "error";
  validationJob?: ValidationJob | null;
  deleteState: "idle" | "deleting";
  tableListScrollTop: number;
  onReportChange: (reportId: string) => void;
  onQueryChange: (query: string) => void;
  onFilterChange: (filter: FilterValue) => void;
  onValidationTypeVisibilityChange: (type: string, visible: boolean) => void;
  onShowAllValidationTypes: () => void;
  onHideAllValidationTypes: () => void;
  onRunValidation: (options: {
    selectedRuleKeys: string[];
    reuseExisting: boolean;
    includeProfileLlm: boolean;
    includeLanguageLlm: boolean;
    sourceValidationRunId?: number;
  }) => Promise<boolean>;
  onStopValidation?: () => void;
  onDeleteReport: (report: ReportOption) => Promise<boolean>;
  onConfirmIncrementDraft?: () => Promise<boolean>;
  onSelect: (tableId: string) => void;
  onOpen: (tableId: string) => void;
  onTableListScrollTopChange: (scrollTop: number) => void;
}

export function ReportWorkspace({
  datasetLabel,
  summary,
  reviewStage = "validated",
  availableReports,
  tables,
  selectedTableId,
  selectedReportId,
  selectedTableDetail,
  query,
  filter,
  validationTypes,
  disabledValidationTypes,
  validationCatalog,
  hiddenValidationTypes,
  validationRunState,
  validationJob,
  deleteState,
  tableListScrollTop,
  onReportChange,
  onQueryChange,
  onFilterChange,
  onValidationTypeVisibilityChange,
  onShowAllValidationTypes,
  onHideAllValidationTypes,
  onRunValidation,
  onStopValidation = () => undefined,
  onDeleteReport,
  onConfirmIncrementDraft,
  onSelect,
  onOpen,
  onTableListScrollTopChange,
}: ReportWorkspaceProps) {
  // Validation-type choices define the population represented by the summary
  // cards.  A status-card click only narrows the list below; it must not
  // recalculate the other status counts to zero.
  const scopedTables = useMemo(() => {
    return tables.filter((table) =>
      matchesWorkspaceFilter(table, query, "all", hiddenValidationTypes, reviewStage),
    );
  }, [hiddenValidationTypes, query, reviewStage, tables]);
  const filteredTables = useMemo(
    () =>
      filter === "all"
        ? scopedTables
        : scopedTables.filter((table) =>
            matchesWorkspaceFilter(table, query, filter, hiddenValidationTypes, reviewStage),
          ),
    [filter, hiddenValidationTypes, query, reviewStage, scopedTables],
  );
  const filteredSummary = useMemo(
    () => summaryWithValidationVisibility(summary, scopedTables),
    [scopedTables, summary],
  );

  const activeId = filteredTables.some((table) => table.id === selectedTableId)
    ? selectedTableId
    : filteredTables[0]?.id ?? "";
  const selectedTable = selectedTableDetail?.id === activeId ? selectedTableDetail : null;

  useEffect(() => {
    if (activeId && selectedTableId !== activeId) {
      onSelect(activeId);
    }
  }, [activeId, onSelect, selectedTableId]);

  function handleSummaryFilterChange(nextFilter: FilterValue) {
    onFilterChange(nextFilter);

    const nextTables = tables.filter((table) =>
      matchesWorkspaceFilter(table, query, nextFilter, hiddenValidationTypes, reviewStage),
    );
    if (nextTables.length > 0 && !nextTables.some((table) => table.id === selectedTableId)) {
      onSelect(nextTables[0].id);
    }
  }

  return (
    <div className="workspace">
      <div className="workspace-sidebar">
        <ReportSummaryPanel
          summary={filteredSummary}
          reviewStage={reviewStage}
          datasetLabel={datasetLabel}
          availableReports={availableReports}
          selectedReportId={selectedReportId || String(summary.report_id ?? "")}
          activeFilter={filter}
          validationTypes={validationTypes}
          disabledValidationTypes={disabledValidationTypes}
          validationCatalog={validationCatalog}
          hiddenValidationTypes={hiddenValidationTypes}
          validationRunState={validationRunState}
          validationJob={validationJob}
          deleteState={deleteState}
          onReportChange={onReportChange}
          onFilterChange={handleSummaryFilterChange}
          onValidationTypeVisibilityChange={onValidationTypeVisibilityChange}
          onShowAllValidationTypes={onShowAllValidationTypes}
          onHideAllValidationTypes={onHideAllValidationTypes}
          onRunValidation={onRunValidation}
          onStopValidation={onStopValidation}
          onDeleteReport={onDeleteReport}
          onConfirmIncrementDraft={onConfirmIncrementDraft}
        />
        <TableList
          reviewStage={reviewStage}
          tables={filteredTables}
          activeTableId={activeId}
          query={query}
          filter={filter}
          scrollTop={tableListScrollTop}
          onQueryChange={onQueryChange}
          onFilterChange={onFilterChange}
          onSelect={onSelect}
          onOpen={onOpen}
          onScrollTopChange={onTableListScrollTopChange}
        />
      </div>
      {selectedTable ? <TablePreview table={selectedTable} onOpen={() => onOpen(selectedTable.id)} /> : null}
    </div>
  );
}
