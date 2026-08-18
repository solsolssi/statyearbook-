import type {
  ReportPayload,
  ReportComparisonSummary,
  ReportDeleteResult,
  SourceDataImportResult,
  SourceStatisticDetail,
  SourceStatisticsOverview,
  StatTable,
  TableContentUpdatePayload,
  ReportEditAccess,
  TableEditSession,
  IncrementalConnectionOverview,
  ValidationCatalogItem,
  ValidationReuseRunOption,
} from "../types";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
const API_BASE_URL = normalizeApiBaseUrl(
  import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL,
);

export interface ReportImportJob {
  id: number;
  report_id: number | null;
  run_id: number | null;
  source_file_name: string;
  status: "queued" | "running" | "completed" | "failed";
  current_stage: string;
  progress_percent: number;
  attempt_count: number;
  error_message: string;
}

export type SourceDataUploadMode = "append_year";

export interface ReportUploadOptions {
  year?: number;
  title?: string;
  mode?: "completed_report_new";
  baseReportId?: number;
  includeLlm?: boolean;
}

export interface SourceDataUploadOptions {
  mode: SourceDataUploadMode;
  baseReportId: number;
  targetYear: number;
  title: string;
  infoFile: File;
  itemFile: File;
  valueFile: File;
  includeLlm?: boolean;
}

export interface ValidationRunResult {
  run_id: number;
  report_id: number;
  tables: number;
  issues: number;
  language_candidates: number;
  language_pending: number;
  language_reused: number;
  language_status: "대기" | "완료";
  selected_rule_keys: string[];
  reused_report_count: number;
  reused_table_count: number;
  reused_check_count: number;
}

export interface TableDownloadCatalogItem {
  id: string;
  code: string;
  title: string;
}

export async function fetchReport(reportId?: string): Promise<ReportPayload> {
  return requestJson<ReportPayload>(
    apiPath("/api/report/overview", { report_id: reportId }),
    undefined,
    "통계연보 데이터를 불러오지 못했습니다.",
  );
}

export async function fetchValidationCatalog(): Promise<ValidationCatalogItem[]> {
  return requestJson<ValidationCatalogItem[]>(
    "/api/validation/catalog",
    undefined,
    "검수 항목 정보를 불러오지 못했습니다.",
  );
}

export async function fetchValidationReuseRuns(
  reportId: number,
): Promise<ValidationReuseRunOption[]> {
  return requestJson<ValidationReuseRunOption[]>(
    apiPath("/api/validation/reuse-runs", { report_id: String(reportId) }),
    undefined,
    "재사용할 검수 실행 목록을 불러오지 못했습니다.",
  );
}

export async function fetchSourceStatistics(): Promise<SourceStatisticsOverview> {
  return requestJson<SourceStatisticsOverview>(
    "/api/source-statistics",
    undefined,
    "통계 원장을 불러오지 못했습니다.",
  );
}

export async function fetchSourceStatistic(
  externalId: string,
  period?: string,
): Promise<SourceStatisticDetail> {
  return requestJson<SourceStatisticDetail>(
    apiPath(`/api/source-statistics/${encodeURIComponent(externalId)}`, { period }),
    undefined,
    "통계 원장 상세 데이터를 불러오지 못했습니다.",
  );
}

export async function fetchTable(tableId: string, reportId?: string): Promise<StatTable> {
  return requestJson<StatTable>(
    apiPath(`/api/tables/${encodeURIComponent(tableId)}`, { report_id: reportId }),
    undefined,
    "통계표 상세 데이터를 불러오지 못했습니다.",
  );
}

export async function fetchTableDownloadCatalog(
  reportId: number,
): Promise<TableDownloadCatalogItem[]> {
  return requestJson<TableDownloadCatalogItem[]>(
    `/api/reports/${reportId}/table-download-catalog`,
    undefined,
    "통계 번호 목록을 불러오지 못했습니다.",
  );
}

export async function fetchReportEditAccess(
  reportId: number,
): Promise<ReportEditAccess> {
  return requestJson<ReportEditAccess>(
    `/api/reports/${reportId}/edit-access`,
    undefined,
    "수정 비밀번호 설정을 불러오지 못했습니다.",
  );
}

export async function saveReportEditPassword(
  reportId: number,
  tableId: string,
  values: { newPassword: string; currentPassword?: string },
): Promise<ReportEditAccess> {
  return requestJson<ReportEditAccess>(
    `/api/reports/${reportId}/tables/${encodeURIComponent(tableId)}/edit-password`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        new_password: values.newPassword,
        current_password: values.currentPassword || undefined,
      }),
    },
    "수정 비밀번호를 저장하지 못했습니다.",
  );
}

export async function authenticateTableEdit(
  reportId: number,
  tableId: string,
  password: string,
): Promise<TableEditSession> {
  return requestJson<TableEditSession>(
    `/api/reports/${reportId}/tables/${encodeURIComponent(tableId)}/edit-session`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    },
    "수정 비밀번호를 확인하지 못했습니다.",
  );
}

export async function updateTableContent(
  reportId: number,
  tableId: string,
  accessToken: string,
  payload: TableContentUpdatePayload,
): Promise<StatTable> {
  return requestJson<StatTable>(
    `/api/reports/${reportId}/tables/${encodeURIComponent(tableId)}`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify(payload),
    },
    "수정한 연보를 저장하지 못했습니다.",
  );
}

export async function cloneStatistic(
  reportId: number,
  tableId: string,
  accessToken: string,
  code: string,
  title: string,
): Promise<StatTable> {
  return requestJson<StatTable>(
    `/api/reports/${reportId}/tables/${encodeURIComponent(tableId)}/clone`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify({ code, title }),
    },
    "통계를 추가하지 못했습니다.",
  );
}

export async function deleteStatistic(
  reportId: number,
  tableId: string,
  accessToken: string,
): Promise<{ deleted_table_count: number }> {
  return requestJson<{ deleted_table_count: number }>(
    `/api/reports/${reportId}/tables/${encodeURIComponent(tableId)}`,
    {
      method: "DELETE",
      headers: { Authorization: `Bearer ${accessToken}` },
    },
    "통계를 삭제하지 못했습니다.",
  );
}

export async function uploadReport(
  file: File,
  options: ReportUploadOptions = {},
): Promise<ReportImportJob> {
  return requestJson<ReportImportJob>(
    apiPath("/api/imports", {
      filename: file.name,
      year: options.year === undefined ? undefined : String(options.year),
      title: options.title,
      mode: options.mode,
      base_report_id:
        options.baseReportId === undefined ? undefined : String(options.baseReportId),
      include_llm: options.includeLlm === undefined ? undefined : String(options.includeLlm),
    }),
    {
      method: "POST",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    },
    "연보 파일을 업로드하지 못했습니다.",
  );
}

export async function compareReports(
  leftReportId: number,
  rightReportId: number,
): Promise<ReportComparisonSummary> {
  return requestJson<ReportComparisonSummary>(
    apiPath("/api/report-comparisons", {
      left_report_id: String(leftReportId),
      right_report_id: String(rightReportId),
    }),
    { method: "POST" },
    "두 연보를 비교하지 못했습니다.",
  );
}

export async function deleteReport(reportId: number): Promise<ReportDeleteResult> {
  return requestJson<ReportDeleteResult>(
    `/api/reports/${reportId}`,
    { method: "DELETE" },
    "연보를 삭제하지 못했습니다.",
  );
}

export async function uploadSourceData(
  options: SourceDataUploadOptions,
): Promise<SourceDataImportResult> {
  const formData = new FormData();
  formData.set("info_file", options.infoFile);
  formData.set("item_file", options.itemFile);
  formData.set("value_file", options.valueFile);
  return requestJson<SourceDataImportResult>(
    apiPath("/api/source-statistics/import", {
      mode: options.mode,
      base_report_id: String(options.baseReportId),
      target_year: String(options.targetYear),
      title: options.title,
      include_llm: options.includeLlm === undefined ? undefined : String(options.includeLlm),
    }),
    { method: "POST", body: formData },
    "증분 데이터를 업로드하지 못했습니다.",
  );
}

export async function setIncrementalMapping(
  reportId: number,
  tableCode: string,
  sourceKey: string,
): Promise<{
  source_key: string;
  applied: boolean;
  applied_cell_count: number;
  message: string;
  reason_code?: string;
}> {
  return requestJson<{
    source_key: string;
    applied: boolean;
    applied_cell_count: number;
    message: string;
    reason_code?: string;
  }>(
    apiPath(`/api/reports/${reportId}/incremental-mappings/${encodeURIComponent(tableCode)}`, {
      source_key: sourceKey,
    }),
    { method: "PUT" },
    "연결 키를 저장하지 못했습니다.",
  );
}

export async function previewIncrementalMapping(
  reportId: number,
  tableCode: string,
  sourceKey: string,
): Promise<{
  source_key: string;
  title?: string;
  compatible: boolean;
  applied_cell_count: number;
  reason_code: string;
  message: string;
  evidence: Record<string, unknown>;
}> {
  return requestJson(
    apiPath(
      `/api/reports/${reportId}/incremental-mappings/${encodeURIComponent(tableCode)}/preview`,
      { source_key: sourceKey },
    ),
    {},
    "연결 키의 반영 결과를 미리 확인하지 못했습니다.",
  );
}

export async function fetchIncrementalConnections(
  reportId: number,
): Promise<IncrementalConnectionOverview> {
  return requestJson<IncrementalConnectionOverview>(
    `/api/reports/${reportId}/incremental-connections`,
    {},
    "증분 연결 현황을 불러오지 못했습니다.",
  );
}

export async function createStatisticFromIncrement(
  reportId: number,
  sourceKey: string,
  tableCode: string,
  title: string,
): Promise<{
  table_id: string;
  table_code: string;
  title: string;
  source_key: string;
  created_cell_count: number;
}> {
  return requestJson(
    apiPath(
      `/api/reports/${reportId}/incremental-connections/${encodeURIComponent(sourceKey)}/create-statistic`,
      { table_code: tableCode, title },
    ),
    { method: "POST" },
    "증분으로 새 통계를 만들지 못했습니다.",
  );
}

export async function keepExistingIncrementTable(
  reportId: number,
  tableCode: string,
): Promise<void> {
  await requestJson(
    `/api/reports/${reportId}/incremental-connections/${encodeURIComponent(tableCode)}/keep-existing`,
    { method: "POST" },
    "기존값 유지 결정을 저장하지 못했습니다.",
  );
}

export async function ignoreUnmatchedIncrement(
  reportId: number,
  sourceKey: string,
): Promise<void> {
  await requestJson(
    `/api/reports/${reportId}/incremental-connections/${encodeURIComponent(sourceKey)}/ignore`,
    { method: "POST" },
    "증분 제외 결정을 저장하지 못했습니다.",
  );
}

export async function confirmIncrementReport(reportId: number): Promise<void> {
  await requestJson<{ confirmed: boolean }>(
    `/api/reports/${reportId}/confirm-increment`,
    { method: "POST" },
    "연보 초안을 확정하지 못했습니다.",
  );
}

export async function runReportValidation(
  reportId: number,
  options: {
    selectedRuleKeys: string[];
    reuseExisting: boolean;
    includeProfileLlm?: boolean;
    includeLanguageLlm?: boolean;
    sourceValidationRunId?: number;
  },
): Promise<ValidationRunResult> {
  return requestJson<ValidationRunResult>(
    apiPath("/api/validation/run", { report_id: String(reportId) }),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        selected_rule_keys: options.selectedRuleKeys,
        reuse_existing: options.reuseExisting,
        include_profile_llm: options.includeProfileLlm ?? false,
        include_language_llm: options.includeLanguageLlm ?? false,
        source_validation_run_id: options.sourceValidationRunId,
      }),
    },
    "연보 검수를 실행하지 못했습니다.",
  );
}

export async function downloadValidationReportArchive(
  reportId: number,
  statuses: string[],
  contents: string[],
): Promise<void> {
  const params = new URLSearchParams();
  for (const status of statuses) {
    params.append("status", status);
  }
  for (const content of contents) {
    params.append("component", content);
  }
  const response = await fetch(
    `${API_BASE_URL}/api/reports/${reportId}/validation-report?${params.toString()}`,
  );
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "검수 리포트를 만들지 못했습니다.");
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `validation-report-${reportId}.zip`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export async function fetchImportJob(jobId: number): Promise<ReportImportJob> {
  return requestJson<ReportImportJob>(
    `/api/imports/${jobId}`,
    undefined,
    "가져오기 작업 상태를 확인하지 못했습니다.",
  );
}

export async function retryImport(jobId: number): Promise<ReportImportJob> {
  return requestJson<ReportImportJob>(
    `/api/imports/${jobId}/retry`,
    { method: "POST" },
    "실패한 연보 처리 작업을 재시도하지 못했습니다.",
  );
}

export async function waitForImport(
  jobId: number,
  { automaticRetries = 1 }: { automaticRetries?: number } = {},
): Promise<ReportImportJob> {
  let retries = 0;
  for (let attempt = 0; attempt < 400; attempt += 1) {
    const job = await fetchImportJob(jobId);
    if (job.status === "completed") {
      return job;
    }
    if (job.status === "failed") {
      if (retries < automaticRetries) {
        retries += 1;
        await retryImport(jobId);
        await delay(1000);
        continue;
      }
      throw new Error(job.error_message || "연보 처리 중 오류가 발생했습니다.");
    }
    await delay(1500);
  }
  throw new Error("연보 처리 시간이 초과되었습니다. 작업 상태를 다시 확인해 주세요.");
}

function apiPath(path: string, values: Record<string, string | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value) {
      params.set(key, value);
    }
  }
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

async function requestJson<T>(
  path: string,
  init: RequestInit | undefined,
  fallbackMessage: string,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? fallbackMessage);
  }
  return response.json() as Promise<T>;
}

function normalizeApiBaseUrl(value: string): string {
  const normalized = value
    .trim()
    .replace(/^VITE_API_BASE_URL\s*=\s*/, "")
    .replace(/\/+$/, "");
  return normalized || DEFAULT_API_BASE_URL;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, milliseconds));
}
