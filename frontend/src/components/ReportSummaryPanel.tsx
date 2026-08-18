import { useState } from "react";
import { CheckCircle2, ClipboardCheck, Database, Download, FileSpreadsheet, LoaderCircle, Trash2 } from "lucide-react";

import type {
  ReportOption,
  ReportSummary,
  TableStatus,
  ValidationCatalogItem,
} from "../types";
import { ValidationTypeFilter } from "./ValidationTypeFilter";
import { ValidationRunDialog } from "./ValidationRunDialog";
import { ReportWorkbookDownloadDialog } from "./ReportWorkbookDownloadDialog";
import { ValidationReportDownloadDialog } from "./ValidationReportDownloadDialog";

type SummaryFilter = TableStatus | "all";

interface ReportSummaryPanelProps {
  summary: ReportSummary;
  datasetLabel: string;
  availableReports: ReportOption[];
  selectedReportId: string;
  activeFilter: TableStatus | "all" | "has_issues";
  validationTypes: string[];
  disabledValidationTypes: ReadonlySet<string>;
  validationCatalog: ValidationCatalogItem[];
  hiddenValidationTypes: ReadonlySet<string>;
  validationRunState: "idle" | "running" | "error";
  deleteState: "idle" | "deleting";
  onReportChange: (reportId: string) => void;
  onFilterChange: (filter: SummaryFilter) => void;
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
  onDeleteReport: (report: ReportOption) => Promise<boolean>;
  onConfirmIncrementDraft?: () => Promise<boolean>;
}

const summaryCards: Array<{
  filter: SummaryFilter;
  label: string;
  countKey: keyof Pick<
    ReportSummary,
    "total_tables" | "normal_count" | "needs_review_count" | "suspected_error_count"
  >;
  tone?: "normal" | "review" | "error";
}> = [
  { filter: "all", label: "전체 표", countKey: "total_tables" },
  { filter: "normal", label: "정상", countKey: "normal_count", tone: "normal" },
  { filter: "needs_review", label: "확인 필요", countKey: "needs_review_count", tone: "review" },
  { filter: "suspected_error", label: "오류 의심", countKey: "suspected_error_count", tone: "error" },
];

export function ReportSummaryPanel({
  summary,
  datasetLabel,
  availableReports,
  selectedReportId,
  activeFilter,
  validationTypes,
  disabledValidationTypes,
  validationCatalog,
  hiddenValidationTypes,
  validationRunState,
  deleteState,
  onReportChange,
  onFilterChange,
  onValidationTypeVisibilityChange,
  onShowAllValidationTypes,
  onHideAllValidationTypes,
  onRunValidation,
  onDeleteReport,
  onConfirmIncrementDraft,
}: ReportSummaryPanelProps) {
  const [validationDialogOpen, setValidationDialogOpen] = useState(false);
  const [validationReportDialogOpen, setValidationReportDialogOpen] = useState(false);
  const [downloadDialogOpen, setDownloadDialogOpen] = useState(false);
  const currentReportOption =
    summary.report_id && summary.report_id > 0
      ? {
          id: summary.report_id,
          year: Number(summary.base_year) || 0,
          title: summary.file_name || `${summary.base_year} ${datasetLabel}`,
          file_name: summary.file_name,
          imported_at: "",
          table_count: summary.total_tables,
          kind: "published" as const,
        }
      : null;
  const baseReportOptions =
    availableReports.length > 0
      ? availableReports
      : [
          {
            id: summary.report_id ?? 0,
            year: Number(summary.base_year) || 0,
            title: `${summary.base_year} ${datasetLabel}`,
            file_name: summary.file_name,
            imported_at: "",
            table_count: summary.total_tables,
            kind: "published" as const,
          },
        ];
  const reportOptions =
    currentReportOption &&
    !baseReportOptions.some((report) => report.id === currentReportOption.id)
      ? [currentReportOption, ...baseReportOptions]
      : baseReportOptions;
  const selectedReport =
    reportOptions.find((report) => String(report.id) === selectedReportId) ??
    currentReportOption ??
    reportOptions[0];
  const canDeleteSelectedReport = Boolean(
    selectedReport &&
      selectedReport.id > 0 &&
      selectedReport.kind !== "test",
  );
  const canRunValidation = Boolean(
    summary.validation_available !== false && summary.report_id,
  );
  const showValidationTypeFilter = validationTypes.length > 0;
  const canDownloadSelectedReport = Boolean(
    selectedReport &&
      selectedReport.id > 0 &&
      selectedReport.kind !== "test",
  );
  const downloadReports = canDownloadSelectedReport && selectedReport ? [selectedReport] : [];
  const isIncrementDraft = ["incremental_draft", "upload_draft"].includes(summary.origin_kind ?? "");

  async function handleDeleteClick() {
    if (!selectedReport || !canDeleteSelectedReport || deleteState === "deleting") {
      return;
    }
    const confirmed = window.confirm(
      [
        `"${selectedReport.title}" 연보를 삭제할까요?`,
        `표 ${selectedReport.table_count.toLocaleString()}개와 연결된 검수 결과가 함께 삭제됩니다.`,
        "이 작업은 되돌릴 수 없습니다.",
      ].join("\n"),
    );
    if (!confirmed) {
      return;
    }
    await onDeleteReport(selectedReport);
  }

  return (
    <section className="report-summary-panel" aria-label="자료 및 검수 요약">
      <div className="dataset-selector">
        <label>
          <Database aria-hidden="true" size={16} />
          <select value={selectedReportId} onChange={(event) => onReportChange(event.target.value)}>
            {reportOptions.map((report) => (
              <option key={report.id} value={report.id}>
                {report.title} · {report.table_count}개 표
                {report.kind === "test" ? " · 검수 없음" : ""}
              </option>
            ))}
          </select>
        </label>
        {canDeleteSelectedReport ? (
          <button
            className="report-delete-button"
            type="button"
            disabled={deleteState === "deleting"}
            onClick={() => void handleDeleteClick()}
          >
            {deleteState === "deleting" ? (
              <LoaderCircle className="is-spinning" aria-hidden="true" size={15} />
            ) : (
              <Trash2 aria-hidden="true" size={15} />
            )}
            <span>{deleteState === "deleting" ? "삭제 중" : "연보 삭제"}</span>
          </button>
        ) : null}
        {isIncrementDraft && onConfirmIncrementDraft ? (
          <button
            className="summary-confirm-button"
            type="button"
            onClick={() => void onConfirmIncrementDraft()}
          >
            <CheckCircle2 aria-hidden="true" size={17} />
            연보 확정
          </button>
        ) : null}
        {canDownloadSelectedReport && !isIncrementDraft ? (
          <button
            className="summary-download-button"
            type="button"
            onClick={() => setDownloadDialogOpen(true)}
          >
            <Download aria-hidden="true" size={17} />
            <span>연보 다운</span>
          </button>
        ) : null}
      </div>

      <div className="mini-summary-grid">
        {summaryCards.map((card) => (
          <button
            className={[
              "mini-summary-card",
              card.tone ? `mini-summary-card--${card.tone}` : "",
              activeFilter === card.filter ? "is-active" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            key={card.filter}
            type="button"
            onClick={() => onFilterChange(card.filter)}
          >
            <span>
              {summary.validation_scope === "none" && card.label === "정상"
                  ? "검수 전"
                  : card.label}
            </span>
            <strong>{summary[card.countKey]}</strong>
          </button>
        ))}
      </div>

      {showValidationTypeFilter || canRunValidation ? (
        <div className="summary-control-row">
          {showValidationTypeFilter ? (
            <ValidationTypeFilter
              types={validationTypes}
              hiddenTypes={hiddenValidationTypes}
              disabledTypes={disabledValidationTypes}
              onVisibilityChange={onValidationTypeVisibilityChange}
              onShowAll={onShowAllValidationTypes}
              onHideAll={onHideAllValidationTypes}
            />
          ) : null}
          {canRunValidation ? (
            <div className="report-validation-actions">
              {summary.validation_scope !== "none" ? (
                <button
                  className="report-validation-export-button"
                  type="button"
                  onClick={() => setValidationReportDialogOpen(true)}
                >
                  <FileSpreadsheet aria-hidden="true" size={17} />
                  <span>검수 리포트</span>
                </button>
              ) : null}
              <button
                type="button"
                disabled={validationRunState === "running"}
                onClick={() => setValidationDialogOpen(true)}
              >
                {validationRunState === "running" ? (
                  <LoaderCircle className="is-spinning" aria-hidden="true" size={17} />
                ) : (
                  <ClipboardCheck aria-hidden="true" size={17} />
                )}
                <span>
                  {validationRunState === "running"
                    ? "검수 진행 중"
                    : "검수 진행"}
                </span>
              </button>
            </div>
          ) : null}
        </div>
      ) : null}

      {validationDialogOpen && selectedReport ? (
        <ValidationRunDialog
          reportId={selectedReport.id}
          reportTitle={selectedReport.title}
          catalog={validationCatalog}
          state={validationRunState}
          onClose={() => setValidationDialogOpen(false)}
          onRun={onRunValidation}
        />
      ) : null}
      {validationReportDialogOpen && selectedReport ? (
        <ValidationReportDownloadDialog
          reportId={selectedReport.id}
          reportTitle={selectedReport.title}
          onClose={() => setValidationReportDialogOpen(false)}
        />
      ) : null}
      {downloadDialogOpen ? (
        <ReportWorkbookDownloadDialog
          reports={downloadReports}
          selectedReportId={selectedReportId}
          onClose={() => setDownloadDialogOpen(false)}
        />
      ) : null}

    </section>
  );
}
