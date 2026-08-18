import { useCallback, useState } from "react";

import {
  uploadReport,
  uploadSourceData,
  waitForImport,
  type ReportImportJob,
  type SourceDataUploadMode,
} from "../api/reportApi";

export type UploadSubmission =
  | {
      mode: "completed_report_new";
      baseReportId?: number;
      targetYear: number;
      title: string;
      file: File;
      includeLlm: boolean;
    }
  | {
      mode: SourceDataUploadMode;
      baseReportId: number;
      targetYear: number;
      title: string;
      infoFile: File;
      itemFile: File;
      valueFile: File;
      includeLlm: boolean;
    };

export type UploadState = "idle" | "uploading" | "error";

export function useReportImport(onCompleted: (job: ReportImportJob) => void) {
  const [uploadState, setUploadState] = useState<UploadState>("idle");

  const upload = useCallback(
    async (submission: UploadSubmission): Promise<boolean> => {
      setUploadState("uploading");
      try {
        if (submission.mode === "completed_report_new") {
          const queued = await uploadReport(submission.file, {
            year: submission.targetYear,
            title: submission.title,
            mode: submission.mode,
            baseReportId: submission.baseReportId,
            includeLlm: submission.includeLlm,
          });
          const completed = await waitForImport(queued.id);
          onCompleted(completed);
        } else {
          const result = await uploadSourceData({
            mode: submission.mode,
            baseReportId: submission.baseReportId,
            targetYear: submission.targetYear,
            title: submission.title,
            infoFile: submission.infoFile,
            itemFile: submission.itemFile,
            valueFile: submission.valueFile,
            includeLlm: submission.includeLlm,
          });
          window.alert(
            [
              `${submission.targetYear}년 연보 초안을 생성했습니다.`,
              `업로드 데이터: 표 ${result.datasets.toLocaleString()}개 · 항목 ${result.items.toLocaleString()}개 · 값 ${result.values.toLocaleString()}개`,
              `반영: 완료 ${result.generated_table_count.toLocaleString()}개 · 증분 연결 ${result.review_table_count.toLocaleString()}개`,
              "선택한 기준 연보와 이번 증분 파일만 사용했습니다.",
              submission.includeLlm && result.llm_assistance
                ? result.llm_assistance.available
                  ? `LLM 보조: 자동 적용 ${result.llm_assistance.applied.toLocaleString()}개 · 검토 제안 ${result.llm_assistance.proposed.toLocaleString()}개`
                  : result.llm_assistance.message || "LLM 설정이 없어 기존 처리 결과를 유지했습니다."
                : "",
              result.new_table_count > 0
                ? `신규 통계 임시 표 ${result.new_table_count.toLocaleString()}개`
                : "",
              result.deleted_table_count > 0
                ? `삭제 명세 반영 ${result.deleted_table_count.toLocaleString()}개`
                : "",
            ]
              .filter(Boolean)
              .join("\n"),
          );
          onCompleted({
            id: 0,
            report_id: result.generated_report_id,
            run_id: null,
            source_file_name: "증분 업로드 연보 초안",
            status: "completed",
            current_stage: "source_data_import",
            progress_percent: 100,
            attempt_count: 1,
            error_message: "",
          });
        }
        setUploadState("idle");
        return true;
      } catch (error) {
        setUploadState("error");
        window.alert(error instanceof Error ? error.message : "연보 처리 중 오류가 발생했습니다.");
        return false;
      }
    },
    [onCompleted],
  );

  return { upload, uploadState };
}
