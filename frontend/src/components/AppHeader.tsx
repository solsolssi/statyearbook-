import { useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpenCheck,
  Database,
  FileText,
  LoaderCircle,
  RefreshCcw,
  Scale,
  Upload,
  X,
} from "lucide-react";

import { compareReports } from "../api/reportApi";
import type {
  ReportComparisonSummary,
  ReportOption,
  ReportTableDifference,
} from "../types";
import type { UploadSubmission } from "../hooks/useReportImport";

export type AppSection = "annual" | "source" | "keyStats" | "press";

interface AppHeaderProps {
  activeSection: AppSection;
  availableReports: ReportOption[];
  availableTemplates: ReportOption[];
  selectedReportId: string;
  onSectionChange: (section: AppSection) => void;
  onUpload: (submission: UploadSubmission) => void;
  uploadState: "idle" | "uploading" | "error";
}

type UploadMode = UploadSubmission["mode"];

interface UploadModeOption {
  id: UploadMode;
  title: string;
  detail: string;
  icon: typeof Database;
}

const navItems: Array<{ id: AppSection; label: string }> = [
  { id: "annual", label: "통계 연보" },
  { id: "source", label: "통계 원장" },
  { id: "keyStats", label: "주요통계집" },
  { id: "press", label: "보도자료" },
];

const uploadModes: UploadModeOption[] = [
  {
    id: "append_year",
    title: "기준 연보에 새 연도 원장 추가",
    detail: "선택한 연보의 형식을 기준으로 다음 연도 원장 데이터를 반영합니다.",
    icon: Database,
  },
  {
    id: "completed_report_new",
    title: "완성 연보 새로 업로드",
    detail: "HWPX, MD, 완성 엑셀 연보를 새 연보로 저장합니다.",
    icon: FileText,
  },
  {
    id: "completed_report_update",
    title: "완성 연보 수정본 반영",
    detail: "기준 연보와 달라진 표를 찾을 수 있도록 수정본을 별도 연보로 저장합니다.",
    icon: RefreshCcw,
  },
];

export function AppHeader({
  activeSection,
  availableReports,
  availableTemplates,
  selectedReportId,
  onSectionChange,
  onUpload,
  uploadState,
}: AppHeaderProps) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [comparisonOpen, setComparisonOpen] = useState(false);

  return (
    <header className="app-header">
      <div className="app-logo">
        <BookOpenCheck aria-hidden="true" size={22} />
        <span>통계 연보 검수 보조</span>
      </div>

      <div className="app-header__actions">
        <button
          className="report-upload-button"
          type="button"
          disabled={uploadState === "uploading"}
          onClick={() => setDialogOpen(true)}
        >
          {uploadState === "uploading" ? (
            <LoaderCircle className="is-spinning" aria-hidden="true" size={18} />
          ) : (
            <Upload aria-hidden="true" size={18} />
          )}
          <span>{uploadState === "uploading" ? "처리 중" : "연보 업로드"}</span>
        </button>
        <button
          className="report-upload-button report-compare-button"
          type="button"
          onClick={() => setComparisonOpen(true)}
        >
          <Scale aria-hidden="true" size={18} />
          <span>연보 비교</span>
        </button>
        {dialogOpen ? (
          <UploadDecisionDialog
            availableReports={availableReports}
            availableTemplates={availableTemplates}
            selectedReportId={selectedReportId}
            uploadState={uploadState}
            onClose={() => setDialogOpen(false)}
            onUpload={(submission) => {
              onUpload(submission);
              setDialogOpen(false);
            }}
          />
        ) : null}
        {comparisonOpen ? (
          <ReportComparisonDialog
            reports={availableReports.filter((report) => report.kind !== "test")}
            onClose={() => setComparisonOpen(false)}
          />
        ) : null}
        <nav className="app-nav" aria-label="주요 메뉴">
          {navItems.map((item) => (
            <button
              className={activeSection === item.id ? "is-active" : ""}
              key={item.id}
              type="button"
              onClick={() => onSectionChange(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </div>
    </header>
  );
}

interface UploadDecisionDialogProps {
  availableReports: ReportOption[];
  availableTemplates: ReportOption[];
  selectedReportId: string;
  uploadState: "idle" | "uploading" | "error";
  onClose: () => void;
  onUpload: (submission: UploadSubmission) => void;
}

function UploadDecisionDialog({
  availableReports,
  availableTemplates,
  selectedReportId,
  uploadState,
  onClose,
  onUpload,
}: UploadDecisionDialogProps) {
  const baseReports = useMemo(
    () => [
      ...availableReports.filter((report) => report.kind !== "test"),
      ...availableTemplates,
    ],
    [availableReports, availableTemplates],
  );
  const fallbackReport = baseReports[0];
  const selectedReport =
    baseReports.find((report) => String(report.id) === selectedReportId) ?? fallbackReport;
  const [mode, setMode] = useState<UploadMode>("append_year");
  const [baseReportId, setBaseReportId] = useState(
    selectedReport ? String(selectedReport.id) : "",
  );
  const baseReport = baseReports.find((report) => String(report.id) === baseReportId);
  const [targetYear, setTargetYear] = useState(
    String(baseReport ? baseReport.year + 1 : new Date().getFullYear()),
  );
  const [reportTitle, setReportTitle] = useState(
    `${baseReport ? baseReport.year + 1 : new Date().getFullYear()} 행정안전통계연보`,
  );
  const [completedFile, setCompletedFile] = useState<File | null>(null);
  const [sourceFiles, setSourceFiles] = useState<File[]>([]);
  const completedInputRef = useRef<HTMLInputElement>(null);
  const sourceInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!baseReport) {
      return;
    }
    setTargetYear(
      String(
        mode === "append_year"
          ? baseReport.year + 1
          : mode === "completed_report_new"
            ? new Date().getFullYear()
            : baseReport.year,
      ),
    );
  }, [baseReport, mode]);

  useEffect(() => {
    const year = /^\d{4}$/.test(targetYear)
      ? targetYear
      : String(new Date().getFullYear());
    setReportTitle(
      mode === "completed_report_update" && baseReport
        ? `${baseReport.title} 수정본`
        : `${year} 행정안전통계연보`,
    );
  }, [baseReport, mode, targetYear]);

  const needsBaseReport = mode !== "completed_report_new";
  const sourceFileSet = classifySourceFiles(sourceFiles);
  const canSubmit =
    (!needsBaseReport || Boolean(baseReport)) &&
    /^\d{4}$/.test(targetYear) &&
    Boolean(reportTitle.trim()) &&
    (mode === "completed_report_new" || mode === "completed_report_update"
      ? Boolean(completedFile)
      : Boolean(sourceFileSet.infoFile && sourceFileSet.itemFile && sourceFileSet.valueFile));

  function submit() {
    if (!canSubmit || (needsBaseReport && !baseReport)) {
      return;
    }
    const parsedYear = Number(targetYear);
    if (mode === "completed_report_new") {
      if (!completedFile) {
        return;
      }
      onUpload({
        mode,
        targetYear: parsedYear,
        title: reportTitle.trim(),
        file: completedFile,
      });
      return;
    }
    if (mode === "completed_report_update") {
      if (!completedFile || !baseReport) {
        return;
      }
      onUpload({
        mode,
        baseReportId: baseReport.id,
        targetYear: parsedYear,
        title: reportTitle.trim(),
        file: completedFile,
      });
      return;
    }
    if (!baseReport || !sourceFileSet.infoFile || !sourceFileSet.itemFile || !sourceFileSet.valueFile) {
      return;
    }
    onUpload({
      mode,
      baseReportId: baseReport.id,
      targetYear: parsedYear,
      title: reportTitle.trim(),
      infoFile: sourceFileSet.infoFile,
      itemFile: sourceFileSet.itemFile,
      valueFile: sourceFileSet.valueFile,
    });
  }

  return (
    <div className="upload-dialog-backdrop" role="presentation">
      <section
        className="upload-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="upload-dialog-title"
      >
        <div className="upload-dialog__header">
          <div>
            <span className="section-label">연보 업로드</span>
            <h2 id="upload-dialog-title">업로드 기준 선택</h2>
          </div>
          <button className="icon-button" type="button" aria-label="닫기" onClick={onClose}>
            <X aria-hidden="true" size={20} />
          </button>
        </div>

        <div className="upload-mode-grid">
          {uploadModes.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={mode === item.id ? "upload-mode-card is-selected" : "upload-mode-card"}
                key={item.id}
                type="button"
                onClick={() => {
                  setMode(item.id);
                  setCompletedFile(null);
                  setSourceFiles([]);
                }}
              >
                <Icon aria-hidden="true" size={20} />
                <span>{item.title}</span>
                <small>{item.detail}</small>
              </button>
            );
          })}
        </div>

        <div className="upload-dialog__form">
          <div className="upload-dialog__form-row">
            <label className="upload-dialog__year-field">
              <span>대상 연도</span>
              <input
                type="number"
                min="1900"
                max="2200"
                value={targetYear}
                onChange={(event) => setTargetYear(event.target.value)}
              />
            </label>
            {needsBaseReport ? (
              <label>
                <span>기준 연보</span>
                <select value={baseReportId} onChange={(event) => setBaseReportId(event.target.value)}>
                  {baseReports.map((report) => (
                    <option key={report.id} value={report.id}>
                      {report.year}년 · {report.file_name || report.title}
                      {report.kind === "template" ? " (숨김 템플릿)" : ""}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
          </div>
          <div className="upload-dialog__form-row upload-dialog__form-row--title">
            <label>
              <span>연보 이름</span>
              <input
                type="text"
                value={reportTitle}
                maxLength={120}
                placeholder="리스트에 표시할 연보 이름"
                onChange={(event) => setReportTitle(event.target.value)}
              />
            </label>
          </div>
        </div>

        {mode === "completed_report_new" || mode === "completed_report_update" ? (
          <div className="upload-file-picker">
            <input
              ref={completedInputRef}
              className="visually-hidden"
              type="file"
              accept=".xlsx,.hwpx,.md"
              onChange={(event) => setCompletedFile(event.target.files?.[0] ?? null)}
            />
            <button type="button" onClick={() => completedInputRef.current?.click()}>
              <Upload aria-hidden="true" size={18} />
              <span>연보 파일 선택</span>
            </button>
            <p>{completedFile ? completedFile.name : "HWPX, MD, XLSX 파일 1개를 선택하세요."}</p>
          </div>
        ) : (
          <div className="upload-file-picker">
            <input
              ref={sourceInputRef}
              className="visually-hidden"
              type="file"
              accept=".xls,.xlsx"
              multiple
              onChange={(event) => setSourceFiles(Array.from(event.target.files ?? []))}
            />
            <button type="button" onClick={() => sourceInputRef.current?.click()}>
              <Upload aria-hidden="true" size={18} />
              <span>원장 엑셀 3개 선택</span>
            </button>
            <SourceFileStatus files={sourceFileSet} />
          </div>
        )}

        <div className="upload-dialog__footer">
          <button type="button" className="secondary-button" onClick={onClose}>
            취소
          </button>
          <button
            type="button"
            className="primary-button"
            disabled={!canSubmit || uploadState === "uploading"}
            onClick={submit}
          >
            {uploadState === "uploading" ? "업로드 중" : "업로드 시작"}
          </button>
        </div>
      </section>
    </div>
  );
}

function ReportComparisonDialog({
  reports,
  onClose,
}: {
  reports: ReportOption[];
  onClose: () => void;
}) {
  const [leftId, setLeftId] = useState(String(reports[0]?.id ?? ""));
  const [rightId, setRightId] = useState(String(reports[1]?.id ?? ""));
  const [result, setResult] = useState<ReportComparisonSummary | null>(null);
  const [loading, setLoading] = useState(false);

  async function runComparison() {
    if (!leftId || !rightId || leftId === rightId) {
      return;
    }
    setLoading(true);
    try {
      setResult(await compareReports(Number(leftId), Number(rightId)));
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "연보 비교 중 오류가 발생했습니다.");
    } finally {
      setLoading(false);
    }
  }

  const differences = result?.tables.filter((table) => table.change_type !== "matching") ?? [];
  return (
    <div className="upload-dialog-backdrop" role="presentation">
      <section className="upload-dialog comparison-dialog" role="dialog" aria-modal="true">
        <div className="upload-dialog__header">
          <div>
            <span className="section-label">재현 결과 확인</span>
            <h2>두 연보 비교</h2>
          </div>
          <button className="icon-button" type="button" aria-label="닫기" onClick={onClose}>
            <X aria-hidden="true" size={20} />
          </button>
        </div>
        {reports.length < 2 ? (
          <p className="comparison-empty">비교하려면 연보를 두 개 이상 업로드해 주세요.</p>
        ) : (
          <>
            <div className="upload-dialog__form">
              <label>
                <span>기준 연보</span>
                <select value={leftId} onChange={(event) => setLeftId(event.target.value)}>
                  {reports.map((report) => (
                    <option key={report.id} value={report.id}>{report.year}년 · {report.file_name}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>비교 연보</span>
                <select value={rightId} onChange={(event) => setRightId(event.target.value)}>
                  {reports.map((report) => (
                    <option key={report.id} value={report.id}>{report.year}년 · {report.file_name}</option>
                  ))}
                </select>
              </label>
            </div>
            {result ? (
              <>
                <div className="comparison-summary">
                  <span>일치 <strong>{result.matching_table_count}</strong></span>
                  <span>변경 <strong>{result.changed_table_count}</strong></span>
                  <span>추가 <strong>{result.added_table_count}</strong></span>
                  <span>삭제 <strong>{result.deleted_table_count}</strong></span>
                  <span>셀 차이 <strong>{result.changed_cell_count}</strong></span>
                </div>
                <div className="comparison-table-list">
                  {differences.length === 0 ? <p>모든 표와 셀이 일치합니다.</p> : differences.map((table) => (
                    <div key={table.table_code}>
                      <div>
                        <strong>{table.table_code}</strong>
                        <span>{comparisonLabel(table.change_type)} · 셀 {table.changed_cell_count}개</span>
                      </div>
                      {table.cell_differences.length > 0 ? (
                        <ul>
                          {table.cell_differences.slice(0, 5).map((cell) => (
                            <li key={`${cell.row_index}-${cell.col_index}`}>
                              {cell.row_index + 1}행 {cell.col_index + 1}열:
                              {" “"}{cell.left_value || "(빈 값)"}” → “{cell.right_value || "(빈 값)"}”
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  ))}
                </div>
              </>
            ) : null}
          </>
        )}
        <div className="upload-dialog__footer">
          <button type="button" className="secondary-button" onClick={onClose}>닫기</button>
          <button
            type="button"
            className="primary-button"
            disabled={reports.length < 2 || !leftId || !rightId || leftId === rightId || loading}
            onClick={() => void runComparison()}
          >
            {loading ? "비교 중" : "비교 실행"}
          </button>
        </div>
      </section>
    </div>
  );
}

function comparisonLabel(changeType: ReportTableDifference["change_type"]): string {
  return {
    matching: "일치",
    modified: "변경",
    added: "추가",
    deleted: "삭제",
  }[changeType];
}

function SourceFileStatus({
  files,
}: {
  files: {
    infoFile: File | null;
    itemFile: File | null;
    valueFile: File | null;
  };
}) {
  const parts = [
    `표정보: ${files.infoFile?.name ?? "미선택"}`,
    `표항목: ${files.itemFile?.name ?? "미선택"}`,
    `표데이터: ${files.valueFile?.name ?? "미선택"}`,
  ];
  return (
    <div className="source-file-status">
      <span className={files.infoFile && files.itemFile && files.valueFile ? "is-ready" : ""}>
        {parts.join(" · ")}
      </span>
    </div>
  );
}

function classifySourceFiles(files: File[]): {
  infoFile: File | null;
  itemFile: File | null;
  valueFile: File | null;
} {
  return {
    infoFile: files.find((file) => file.name.includes("표정보")) ?? null,
    itemFile: files.find((file) => file.name.includes("표항목")) ?? null,
    valueFile: files.find((file) => file.name.includes("표데이터")) ?? null,
  };
}
