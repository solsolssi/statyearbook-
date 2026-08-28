import { useCallback, useMemo, useRef, useState } from "react";

import { AppHeader, type AppSection } from "./components/AppHeader";
import { DetailView } from "./components/DetailView";
import { PasswordSettingsPage } from "./components/PasswordSettingsPage";
import { ReportWorkspace } from "./components/ReportWorkspace";
import { SourceStatisticsPage } from "./components/SourceStatisticsPage";
import { useReport } from "./hooks/useReport";
import { useReportImport } from "./hooks/useReportImport";
import { useReportValidation } from "./hooks/useReportValidation";
import { useValidationCatalog } from "./hooks/useValidationCatalog";
import { confirmIncrementReport, deleteReport, fetchTable } from "./api/reportApi";
import type { ReportOption, StatTable, TableStatus } from "./types";
import {
  DEFAULT_HIDDEN_VALIDATION_TYPES,
  INCREMENTAL_REVIEW_TYPES,
  OPTIONAL_VALIDATION_TYPES,
  VALIDATION_CHECK_TYPES,
  activeValidationTypesForTables,
  reportReviewStage,
  summaryWithValidationVisibility,
  tablesWithValidationVisibility,
  validationTypesForTables,
} from "./utils/validationVisibility";
import "./styles/global.css";

type FilterValue = TableStatus | "all" | "has_issues";

export default function App() {
  const [activeSection, setActiveSection] = useState<AppSection>("annual");
  const [selectedTableId, setSelectedTableId] = useState<string>("");
  const [detailTableId, setDetailTableId] = useState<string | null>(null);
  const [detailTable, setDetailTable] = useState<StatTable | null>(null);
  const [detailStatus, setDetailStatus] = useState<"idle" | "loading" | "error">("idle");
  const [selectedTableDetail, setSelectedTableDetail] = useState<StatTable | null>(null);
  const selectedTableRequestRef = useRef("");
  const [selectedReportId, setSelectedReportId] = useState("");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FilterValue>("all");
  const [tableListScrollTop, setTableListScrollTop] = useState(0);
  const [deleteState, setDeleteState] = useState<"idle" | "deleting">("idle");
  const [hiddenValidationTypes, setHiddenValidationTypes] = useState<Set<string>>(
    () => new Set(DEFAULT_HIDDEN_VALIDATION_TYPES),
  );
  const [reportRefreshKey, setReportRefreshKey] = useState(0);
  const report = useReport(selectedReportId || undefined, reportRefreshKey);
  const validationCatalog = useValidationCatalog();
  const catalogTypes = useMemo(
    () => validationCatalog.map((item) => item.label),
    [validationCatalog],
  );

  const handleImportCompleted = useCallback((completed: { report_id: number | null }) => {
    setSelectedReportId(completed.report_id ? String(completed.report_id) : "");
    setSelectedTableId("");
    setDetailTableId(null);
    setDetailTable(null);
    setSelectedTableDetail(null);
    selectedTableRequestRef.current = "";
    setDetailStatus("idle");
    setReportRefreshKey((current) => current + 1);
  }, []);
  const { upload: handleUpload, uploadState } = useReportImport(handleImportCompleted);
  const handleValidationCompleted = useCallback(
    (result: {
      issues: number;
      reused_table_count: number;
      reused_check_count: number;
    }) => {
      setSelectedTableDetail(null);
      setDetailTable(null);
      setDetailTableId(null);
      selectedTableRequestRef.current = "";
      setReportRefreshKey((current) => current + 1);
      window.alert(
        [
          `검수가 완료되었습니다. 확인 대상 ${result.issues.toLocaleString()}건`,
          result.reused_table_count > 0
            ? `동일 표 ${result.reused_table_count.toLocaleString()}개에서 검수 결과 ${result.reused_check_count.toLocaleString()}건을 재사용했습니다.`
            : "",
        ]
          .filter(Boolean)
          .join("\n"),
      );
    },
    [],
  );
  const { runValidation, stopValidation, validationRunState, validationJob } = useReportValidation(
    handleValidationCompleted,
  );

  const rawTables = report.data?.tables ?? [];
  const reviewStage = report.data
    ? reportReviewStage(report.data.summary)
    : "unvalidated";
  const isIncrementDraft = ["incremental_draft", "upload_draft"].includes(
    report.data?.summary.origin_kind ?? "",
  );
  const filterTypeOrder = useMemo(
    () => (
      isIncrementDraft
        ? INCREMENTAL_REVIEW_TYPES
        : [
            ...VALIDATION_CHECK_TYPES,
            ...catalogTypes.filter(
              (type) => !VALIDATION_CHECK_TYPES.includes(
                type as (typeof VALIDATION_CHECK_TYPES)[number],
              ),
            ),
          ]
    ),
    [catalogTypes, isIncrementDraft],
  );
  const validationTypes = useMemo(
    () => {
      if (reviewStage === "unvalidated") {
        return [];
      }
      return validationTypesForTables(
        [
          ...rawTables,
          ...(selectedTableDetail ? [selectedTableDetail] : []),
          ...(detailTable ? [detailTable] : []),
        ],
        filterTypeOrder,
        !isIncrementDraft,
      );
    },
    [detailTable, filterTypeOrder, isIncrementDraft, rawTables, reviewStage, selectedTableDetail],
  );
  const activeValidationTypes = useMemo(
    () =>
      activeValidationTypesForTables([
        ...rawTables,
        ...(selectedTableDetail ? [selectedTableDetail] : []),
        ...(detailTable ? [detailTable] : []),
      ]),
    [detailTable, rawTables, selectedTableDetail],
  );
  const disabledValidationTypes = useMemo(
    () =>
      new Set(
        validationTypes.filter(
          (type) => OPTIONAL_VALIDATION_TYPES.has(type) && !activeValidationTypes.has(type),
        ),
      ),
    [activeValidationTypes, validationTypes],
  );
  const tables = useMemo(
    () => tablesWithValidationVisibility(rawTables, hiddenValidationTypes, reviewStage),
    [hiddenValidationTypes, rawTables, reviewStage],
  );
  const visibleSelectedTableDetail = useMemo(
    () =>
      selectedTableDetail
        ? tablesWithValidationVisibility([selectedTableDetail], hiddenValidationTypes, reviewStage)[0]
        : null,
    [hiddenValidationTypes, reviewStage, selectedTableDetail],
  );
  const visibleDetailTable = useMemo(
    () =>
      detailTable
        ? tablesWithValidationVisibility([detailTable], hiddenValidationTypes, reviewStage)[0]
        : null,
    [detailTable, hiddenValidationTypes, reviewStage],
  );
  const visibleSummary = useMemo(
    () =>
      report.data
        ? summaryWithValidationVisibility(report.data.summary, tables)
        : undefined,
    [report.data, tables],
  );
  async function loadSelectedTableDetail(tableId: string) {
    const requestKey = `${selectedReportId || ""}:${tableId}`;
    selectedTableRequestRef.current = requestKey;
    setSelectedTableDetail(null);

    try {
      const table = await fetchTable(tableId, selectedReportId || undefined);
      if (selectedTableRequestRef.current === requestKey) {
        setSelectedTableDetail(table);
      }
    } catch {
      if (selectedTableRequestRef.current === requestKey) {
        setSelectedTableDetail(null);
      }
    }
  }

  function handleSelect(tableId: string) {
    setSelectedTableId(tableId);
    void loadSelectedTableDetail(tableId);
  }

  async function handleOpen(tableId: string) {
    setSelectedTableId(tableId);
    setDetailTableId(tableId);
    setDetailStatus("loading");
    setDetailTable(selectedTableDetail?.id === tableId ? selectedTableDetail : null);
    try {
      const table =
        selectedTableDetail?.id === tableId
          ? selectedTableDetail
          : await fetchTable(tableId, selectedReportId || undefined);
      setDetailTable(table);
      setDetailStatus("idle");
    } catch (error) {
      setDetailStatus("error");
      setDetailTableId(null);
      window.alert(error instanceof Error ? error.message : "통계표 상세 데이터를 불러오지 못했습니다.");
    }
  }

  function handleReportChange(reportId: string) {
    setSelectedReportId(reportId);
    setSelectedTableId("");
    setDetailTableId(null);
    setDetailTable(null);
    setSelectedTableDetail(null);
    selectedTableRequestRef.current = "";
    setDetailStatus("idle");
    setFilter("all");
    setQuery("");
    setTableListScrollTop(0);
  }

  function handleValidationTypeVisibility(type: string, visible: boolean) {
    setHiddenValidationTypes((current) => {
      const next = new Set(current);
      if (visible) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  }

  async function handleDeleteReport(reportOption: ReportOption): Promise<boolean> {
    if (deleteState === "deleting") {
      return false;
    }
    setDeleteState("deleting");
    try {
      const result = await deleteReport(reportOption.id);
      setSelectedReportId("");
      setSelectedTableId("");
      setDetailTableId(null);
      setDetailTable(null);
      setSelectedTableDetail(null);
      selectedTableRequestRef.current = "";
      setDetailStatus("idle");
      setFilter("all");
      setQuery("");
      setTableListScrollTop(0);
      setReportRefreshKey((current) => current + 1);
      window.alert(
        `${result.title} 연보를 삭제했습니다.\n` +
          `표 ${result.table_count.toLocaleString()}개와 검수 실행 ${result.validation_run_count.toLocaleString()}건이 함께 정리되었습니다.`,
      );
      return true;
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "연보를 삭제하지 못했습니다.");
      return false;
    } finally {
      setDeleteState("idle");
    }
  }

  async function handleConfirmIncrementDraft(): Promise<boolean> {
    const reportId = report.data?.summary.report_id;
    if (!reportId || !["incremental_draft", "upload_draft"].includes(report.data?.summary.origin_kind ?? "")) {
      return false;
    }
    if (!window.confirm("연보 초안을 확정할까요? 확정 후에도 표 수정과 검수는 가능합니다.")) {
      return false;
    }
    try {
      await confirmIncrementReport(reportId);
      setSelectedTableDetail(null);
      setDetailTable(null);
      selectedTableRequestRef.current = "";
      setReportRefreshKey((current) => current + 1);
      window.alert("연보를 확정했습니다. 모든 통계는 검수 전 상태입니다.");
      return true;
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "연보 초안을 확정하지 못했습니다.");
      return false;
    }
  }

  if (report.status === "loading") {
    return <div className="state-page">데이터를 불러오는 중입니다.</div>;
  }

  if (report.status === "error") {
    return <div className="state-page state-page--error">{report.error}</div>;
  }

  if (detailTableId && detailStatus === "loading") {
    return <div className="state-page">상세 데이터를 불러오는 중입니다.</div>;
  }

  if (rawTables.length === 0) {
    return (
      <main className="app-shell">
        <AppHeader
          activeSection={activeSection}
          availableReports={report.data?.available_reports ?? []}
          availableTemplates={report.data?.available_templates ?? []}
          selectedReportId={selectedReportId}
          onSectionChange={setActiveSection}
          onUpload={handleUpload}
          uploadState={uploadState}
        />
        <div className="state-page">데이터가 없습니다.</div>
      </main>
    );
  }

  if (detailTable && visibleDetailTable) {
    const detailReportId = report.data?.summary.report_id ?? undefined;
    const detailIsDraft = ["incremental_draft", "upload_draft"].includes(
      report.data?.summary.origin_kind ?? "",
    );
    return (
      <DetailView
        table={visibleDetailTable}
        reportId={detailReportId && detailReportId > 0 ? detailReportId : undefined}
        isDraft={detailIsDraft}
        validationTypes={validationTypes}
        hiddenValidationTypes={hiddenValidationTypes}
        onValidationTypeVisibilityChange={handleValidationTypeVisibility}
        onShowAllValidationTypes={() => setHiddenValidationTypes(new Set())}
        onHideAllValidationTypes={() => setHiddenValidationTypes(new Set(validationTypes))}
        onBack={() => {
          setDetailTableId(null);
          setDetailTable(null);
          setDetailStatus("idle");
        }}
        onTableSaved={(updated) => {
          setDetailTable(updated);
          setDetailTableId(updated.id);
          setSelectedTableId(updated.id);
          setSelectedTableDetail(updated);
          setReportRefreshKey((current) => current + 1);
        }}
        onTableDeleted={() => {
          setDetailTableId(null);
          setDetailTable(null);
          setSelectedTableId("");
          setSelectedTableDetail(null);
          setDetailStatus("idle");
          setReportRefreshKey((current) => current + 1);
        }}
        onOpenPasswordSettings={() => {
          setDetailTableId(null);
          setDetailTable(null);
          setDetailStatus("idle");
          setActiveSection("editAccess");
        }}
      />
    );
  }

  const reportWorkspace = (
    <ReportWorkspace
      datasetLabel="통계 연보"
      summary={visibleSummary ?? report.data.summary}
      reviewStage={reviewStage}
      availableReports={report.data.available_reports}
      tables={tables}
      selectedTableId={selectedTableId}
      selectedReportId={selectedReportId}
      selectedTableDetail={visibleSelectedTableDetail}
      query={query}
      filter={filter}
      validationTypes={validationTypes}
      disabledValidationTypes={disabledValidationTypes}
      validationCatalog={validationCatalog}
      hiddenValidationTypes={hiddenValidationTypes}
      validationRunState={validationRunState}
      validationJob={validationJob}
      tableListScrollTop={tableListScrollTop}
      onReportChange={handleReportChange}
      onQueryChange={setQuery}
      onFilterChange={setFilter}
      onValidationTypeVisibilityChange={handleValidationTypeVisibility}
      onShowAllValidationTypes={() => setHiddenValidationTypes(new Set())}
      onHideAllValidationTypes={() => setHiddenValidationTypes(new Set(validationTypes))}
      onRunValidation={(options) => {
        const reportId = report.data?.summary.report_id;
        return reportId
          ? runValidation(reportId, options)
          : Promise.resolve(false);
      }}
      onStopValidation={() => void stopValidation()}
      deleteState={deleteState}
      onDeleteReport={handleDeleteReport}
      onConfirmIncrementDraft={handleConfirmIncrementDraft}
      onSelect={handleSelect}
      onOpen={handleOpen}
      onTableListScrollTopChange={setTableListScrollTop}
    />
  );
  const passwordReportId =
    report.data.summary.report_id && report.data.summary.report_id > 0
      ? report.data.summary.report_id
      : report.data.available_reports.find((item) => item.kind !== "test")?.id;

  return (
    <main className="app-shell">
      <AppHeader
        activeSection={activeSection}
        availableReports={report.data.available_reports}
        availableTemplates={report.data.available_templates}
        selectedReportId={selectedReportId}
        onSectionChange={setActiveSection}
        onUpload={handleUpload}
        uploadState={uploadState}
      />

      {activeSection === "annual" ? reportWorkspace : null}
      {activeSection === "source" ? <SourceStatisticsPage /> : null}
      {activeSection === "editAccess" && passwordReportId ? (
        <PasswordSettingsPage
          reportId={passwordReportId}
          availableReports={report.data.available_reports}
          onReportChange={handleReportChange}
        />
      ) : null}
    </main>
  );
}
