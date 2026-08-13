import { useEffect, useState } from "react";
import { X } from "lucide-react";

import {
  fetchTable,
  fetchTableDownloadCatalog,
  type TableDownloadCatalogItem,
} from "../api/reportApi";
import type { ReportOption } from "../types";
import { downloadReportsXlsx, type ReportWorkbookSelection } from "../utils/tableDownload";

type ReportTableCatalogState =
  | { status: "loading"; tables: TableDownloadCatalogItem[]; error?: string }
  | { status: "loaded"; tables: TableDownloadCatalogItem[]; error?: string }
  | { status: "error"; tables: TableDownloadCatalogItem[]; error: string };

type TableSelectionMode = "all" | "custom";

interface ReportWorkbookDownloadDialogProps {
  reports: ReportOption[];
  selectedReportId: string;
  onClose: () => void;
}

export function ReportWorkbookDownloadDialog({
  reports,
  selectedReportId,
  onClose,
}: ReportWorkbookDownloadDialogProps) {
  const report = reports.find((item) => String(item.id) === selectedReportId) ?? reports[0];
  const [tableCatalogs, setTableCatalogs] = useState<Record<number, ReportTableCatalogState>>({});
  const [tableSelectionModes, setTableSelectionModes] = useState<Record<number, TableSelectionMode>>(
    () => (report ? { [report.id]: "all" } : {}),
  );
  const [selectedTableIds, setSelectedTableIds] = useState<Record<number, string[]>>({});
  const [downloadState, setDownloadState] = useState<"idle" | "running">("idle");
  const [progress, setProgress] = useState({ current: 0, total: 0, label: "" });
  const selectedTableCount = report ? selectedCountForReport(report) : 0;
  const isRunning = downloadState === "running";

  useEffect(() => {
    if (!report) {
      return;
    }

    let cancelled = false;
    const reportId = report.id;
    setTableCatalogs((current) => ({
      ...current,
      [reportId]: { status: "loading", tables: [] },
    }));
    void fetchTableDownloadCatalog(reportId)
      .then((tables) => {
        if (cancelled) {
          return;
        }
        setTableCatalogs((current) => ({
          ...current,
          [reportId]: { status: "loaded", tables },
        }));
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        setTableCatalogs((current) => ({
          ...current,
          [reportId]: {
            status: "error",
            tables: [],
            error: error instanceof Error ? error.message : "통계 목록을 불러오지 못했습니다.",
          },
        }));
      });

    return () => {
      cancelled = true;
    };
  }, [report]);

  function tableMode(reportId: number): TableSelectionMode {
    return tableSelectionModes[reportId] ?? "all";
  }

  function selectedCountForReport(report: ReportOption) {
    if (tableMode(report.id) === "all") {
      return tableCatalogs[report.id]?.tables.length || report.table_count;
    }
    return selectedTableIds[report.id]?.length ?? 0;
  }

  function selectedTableIdSet(reportId: number, tables: TableDownloadCatalogItem[]) {
    if (tableMode(reportId) === "all") {
      return new Set(tables.map((table) => table.id));
    }
    return new Set(selectedTableIds[reportId] ?? []);
  }

  function selectAllTables(reportId: number) {
    if (isRunning) {
      return;
    }
    setTableSelectionModes((current) => ({ ...current, [reportId]: "all" }));
    setSelectedTableIds((current) => ({ ...current, [reportId]: [] }));
  }

  function clearTables(reportId: number) {
    if (isRunning) {
      return;
    }
    setTableSelectionModes((current) => ({ ...current, [reportId]: "custom" }));
    setSelectedTableIds((current) => ({ ...current, [reportId]: [] }));
  }

  function toggleTable(reportId: number, tableId: string, tables: TableDownloadCatalogItem[]) {
    if (isRunning) {
      return;
    }
    const currentIds =
      tableMode(reportId) === "all"
        ? tables.map((table) => table.id)
        : selectedTableIds[reportId] ?? [];
    const nextIds = currentIds.includes(tableId)
      ? currentIds.filter((id) => id !== tableId)
      : [...currentIds, tableId];
    setTableSelectionModes((current) => ({ ...current, [reportId]: "custom" }));
    setSelectedTableIds((current) => ({ ...current, [reportId]: nextIds }));
  }

  async function downloadWorkbook() {
    if (!report || selectedTableCount === 0 || isRunning) {
      return;
    }

    setDownloadState("running");
    setProgress({ current: 0, total: selectedTableCount, label: "통계 목록 확인 중" });
    try {
      const selections: ReportWorkbookSelection[] = [];
      let completed = 0;
      const catalog = tableCatalogs[report.id];
      const overview =
        catalog?.status === "loaded"
          ? { tables: catalog.tables }
          : { tables: await fetchTableDownloadCatalog(report.id) };
      const selectedIds =
        tableMode(report.id) === "all"
          ? overview.tables.map((table) => table.id)
          : selectedTableIds[report.id] ?? [];
      const selectedIdSet = new Set(selectedIds);
      const selectedSummaries = overview.tables.filter((table) => selectedIdSet.has(table.id));
      const tables = [];
      for (const table of selectedSummaries) {
        setProgress({
          current: completed,
          total: selectedTableCount,
          label: `${report.year}년 ${table.code} ${table.title}`,
        });
        tables.push(await fetchTable(table.id, String(report.id)));
        completed += 1;
        setProgress({
          current: completed,
          total: selectedTableCount,
          label: `${report.year}년 ${table.code} ${table.title}`,
        });
      }
      if (tables.length > 0) {
        selections.push({ report, tables });
      }
      if (selections.length === 0) {
        window.alert("선택된 통계가 없습니다.");
        return;
      }
      downloadReportsXlsx(selections);
      onClose();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "연보 다운로드 파일을 만들지 못했습니다.");
    } finally {
      setDownloadState("idle");
    }
  }

  return (
    <div className="upload-dialog-backdrop" role="presentation">
      <section className="upload-dialog report-workbook-dialog" role="dialog" aria-modal="true">
        <div className="upload-dialog__header">
          <div>
            <span className="section-label">연보 다운</span>
            <h2>연보 다운로드</h2>
          </div>
          <button
            className="icon-button"
            type="button"
            aria-label="닫기"
            disabled={isRunning}
            onClick={onClose}
          >
            <X aria-hidden="true" size={20} />
          </button>
        </div>

        {!report ? (
          <p className="comparison-empty">다운로드할 연보가 없습니다.</p>
        ) : (
          <>
            <section className="report-workbook-report is-selected">
              <div className="report-workbook-report__header">
                <span>
                  <strong>{report.title}</strong>
                  <small>{report.year}년 통계 번호를 선택하세요.</small>
                </span>
                <strong className="report-workbook-report__selection">
                  {report.year}년 · 통계 {selectedTableCount.toLocaleString()} / {report.table_count.toLocaleString()}개 선택
                </strong>
              </div>
              <div className="report-workbook-report__tables">
                <div className="report-workbook-table-actions">
                  <span>통계 번호 선택</span>
                  <div className="report-workbook-table-action-buttons">
                    <button
                      type="button"
                      disabled={isRunning || tableMode(report.id) === "all"}
                      onClick={() => selectAllTables(report.id)}
                    >
                      전체 선택
                    </button>
                    <button
                      type="button"
                      disabled={isRunning || selectedTableCount === 0}
                      onClick={() => clearTables(report.id)}
                    >
                      선택 해제
                    </button>
                  </div>
                </div>

                {tableCatalogs[report.id]?.status === "loading" || !tableCatalogs[report.id] ? (
                  <p className="report-workbook-state">통계 번호를 불러오는 중입니다.</p>
                ) : tableCatalogs[report.id].status === "error" ? (
                  <p className="report-workbook-state is-error">{tableCatalogs[report.id].error}</p>
                ) : (
                  <div className="report-workbook-table-list">
                    {tableCatalogs[report.id].tables.map((table) => (
                      <label key={table.id}>
                        <input
                          type="checkbox"
                          checked={selectedTableIdSet(report.id, tableCatalogs[report.id].tables).has(table.id)}
                          disabled={isRunning}
                          onChange={() => toggleTable(report.id, table.id, tableCatalogs[report.id].tables)}
                        />
                        <span>
                          <strong>{table.code}</strong>
                          <small>{table.title}</small>
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            </section>

            {isRunning ? (
              <div className="report-workbook-progress" role="status">
                <span>
                  {progress.current.toLocaleString()} / {progress.total.toLocaleString()}
                </span>
                <progress value={progress.current} max={Math.max(progress.total, 1)} />
                <small>{progress.label}</small>
              </div>
            ) : null}
          </>
        )}

        <div className="upload-dialog__footer">
          <button
            type="button"
            className="secondary-button"
            disabled={isRunning}
            onClick={onClose}
          >
            닫기
          </button>
          <button
            type="button"
            className="primary-button"
            disabled={!report || selectedTableCount === 0 || isRunning}
            onClick={() => void downloadWorkbook()}
          >
            {isRunning ? "만드는 중" : "연보 다운"}
          </button>
        </div>
      </section>
    </div>
  );
}
