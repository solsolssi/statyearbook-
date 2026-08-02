import type {
  ReportPayload,
  ReportComparisonSummary,
  ReportDeleteResult,
  ReproductionBuildSummary,
  SourceDataImportResult,
  SourceStatisticDetail,
  SourceStatisticsOverview,
  StatTable,
  ValidationCatalogItem,
  YearbookReproductionOverview,
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
  mode?: "completed_report_new" | "completed_report_update";
  baseReportId?: number;
}

export interface SourceDataUploadOptions {
  mode: SourceDataUploadMode;
  baseReportId: number;
  targetYear: number;
  title: string;
  infoFile: File;
  itemFile: File;
  valueFile: File;
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

export async function fetchYearbookReproduction(
  options: { reportId?: string; reportYear?: number } = {},
): Promise<YearbookReproductionOverview> {
  return requestJson<YearbookReproductionOverview>(
    apiPath("/api/yearbook-reproduction", {
      report_id: options.reportId,
      report_year:
        options.reportYear === undefined ? undefined : String(options.reportYear),
    }),
    undefined,
    "연보 재현 준비 상태를 불러오지 못했습니다.",
  );
}

export async function runYearbookReproduction(
  reportId: number,
): Promise<ReproductionBuildSummary> {
  return requestJson<ReproductionBuildSummary>(
    apiPath("/api/yearbook-reproduction/build", { report_id: String(reportId) }),
    { method: "POST" },
    "연보 셀 재현 비교를 실행하지 못했습니다.",
  );
}

export async function fetchTable(tableId: string, reportId?: string): Promise<StatTable> {
  return requestJson<StatTable>(
    apiPath(`/api/tables/${encodeURIComponent(tableId)}`, { report_id: reportId }),
    undefined,
    "통계표 상세 데이터를 불러오지 못했습니다.",
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
    }),
    { method: "POST", body: formData },
    "통계 원장 데이터를 업로드하지 못했습니다.",
  );
}

export async function runReportValidation(
  reportId: number,
  options: {
    selectedRuleKeys: string[];
    reuseExisting: boolean;
    includeLlm?: boolean;
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
        include_llm: options.includeLlm ?? false,
      }),
    },
    "연보 검수를 실행하지 못했습니다.",
  );
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
