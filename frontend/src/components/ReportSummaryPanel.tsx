import { useState } from "react";
import { ClipboardCheck, Database, LoaderCircle, Trash2 } from "lucide-react";

import type {
  ReportOption,
  ReportSummary,
  TableStatus,
  ValidationCatalogItem,
} from "../types";
import { ValidationTypeFilter } from "./ValidationTypeFilter";
import { ValidationRunDialog } from "./ValidationRunDialog";

type SummaryFilter = TableStatus | "all";

interface ReportSummaryPanelProps {
  summary: ReportSummary;
  datasetLabel: string;
  availableReports: ReportOption[];
  selectedReportId: string;
  activeFilter: TableStatus | "all" | "has_issues";
  validationTypes: string[];
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
    includeLlm: boolean;
  }) => Promise<boolean>;
  onDeleteReport: (report: ReportOption) => Promise<boolean>;
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

const testSummaryLabels: Record<string, string> = {
  "전체 표": "전체 표",
  정상: "생성 가능",
  "확인 필요": "생성 확인",
  "오류 의심": "생성 실패",
};

export function ReportSummaryPanel({
  summary,
  datasetLabel,
  availableReports,
  selectedReportId,
  activeFilter,
  validationTypes,
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
}: ReportSummaryPanelProps) {
  const [validationDialogOpen, setValidationDialogOpen] = useState(false);
  const isTestReport = Boolean(summary.is_test_report);
  const reportOptions =
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
  const selectedReport =
    reportOptions.find((report) => String(report.id) === selectedReportId) ??
    reportOptions[0];
  const canDeleteSelectedReport = Boolean(
    selectedReport &&
      selectedReport.id > 0 &&
      selectedReport.kind !== "test" &&
      !isTestReport,
  );

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
      </div>

      {!isTestReport && summary.validation_available !== false && summary.report_id ? (
        <div className="report-validation-actions">
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
                : summary.validation_scope === "none"
                  ? "검수 진행"
                  : "검수 다시 진행"}
            </span>
          </button>
        </div>
      ) : null}

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
              {isTestReport
                ? testSummaryLabels[card.label]
                : summary.validation_scope === "none" && card.label === "정상"
                  ? "검수 전"
                  : card.label}
            </span>
            <strong>{summary[card.countKey]}</strong>
          </button>
        ))}
      </div>

      {isTestReport ? (
        <div className="test-report-notice">
          <strong>원장 기반 테스트 생성</strong>
          <span>검수는 실행하지 않았으며, 생성하지 못한 표도 기준 레이아웃과 문제를 표시합니다.</span>
        </div>
      ) : summary.validation_scope === "none" ? (
        <div className="test-report-notice update-scope-notice">
          <strong>
            {summary.origin_kind === "ledger_generated"
              ? "원장 기반 연보 생성"
              : "연보 업로드 완료"}
          </strong>
          <span>연보 데이터만 저장된 상태입니다. 위의 검수 진행 버튼에서 항목을 선택해 실행하세요.</span>
        </div>
      ) : summary.validation_scope === "shared" ? (
        <>
          <div className="test-report-notice update-scope-notice">
            <strong>동일 표 검수 결과 공유</strong>
            <span>
              {summary.reused_report_count ?? 0}개 연보에서 동일한
              {" "}{summary.reused_table_count ?? 0}개 표의 검수 결과
              {" "}{summary.reused_check_count ?? 0}건을 재사용했습니다.
            </span>
          </div>
          <ValidationTypeFilter
            types={validationTypes}
            hiddenTypes={hiddenValidationTypes}
            onVisibilityChange={onValidationTypeVisibilityChange}
            onShowAll={onShowAllValidationTypes}
            onHideAll={onHideAllValidationTypes}
          />
        </>
      ) : summary.validation_scope === "selected" ? (
        <>
          <div className="test-report-notice update-scope-notice">
            <strong>선택 항목 검수 완료</strong>
            <span>{summary.selected_validation_keys?.length ?? 0}개 검수 항목을 실행했습니다.</span>
          </div>
          <ValidationTypeFilter
            types={validationTypes}
            hiddenTypes={hiddenValidationTypes}
            onVisibilityChange={onValidationTypeVisibilityChange}
            onShowAll={onShowAllValidationTypes}
            onHideAll={onHideAllValidationTypes}
          />
        </>
      ) : summary.validation_scope === "changed_tables" ? (
        <>
          <div className="test-report-notice update-scope-notice">
            <strong>변경 표 부분 검수</strong>
            <span>
              변경·신규 {summary.changed_table_count ?? 0}개 표만 새로 검수하고,
              동일한 {summary.unchanged_table_count ?? 0}개 표는 기존 검수 결과를 재사용했습니다.
            </span>
          </div>
          <ValidationTypeFilter
            types={validationTypes}
            hiddenTypes={hiddenValidationTypes}
            onVisibilityChange={onValidationTypeVisibilityChange}
            onShowAll={onShowAllValidationTypes}
            onHideAll={onHideAllValidationTypes}
          />
        </>
      ) : (
        <ValidationTypeFilter
          types={validationTypes}
          hiddenTypes={hiddenValidationTypes}
          onVisibilityChange={onValidationTypeVisibilityChange}
          onShowAll={onShowAllValidationTypes}
          onHideAll={onHideAllValidationTypes}
        />
      )}

      {validationDialogOpen && selectedReport ? (
        <ValidationRunDialog
          reportTitle={selectedReport.title}
          catalog={validationCatalog}
          state={validationRunState}
          onClose={() => setValidationDialogOpen(false)}
          onRun={onRunValidation}
        />
      ) : null}

    </section>
  );
}
