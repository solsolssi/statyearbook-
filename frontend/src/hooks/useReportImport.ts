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
    }
  | {
      mode: SourceDataUploadMode;
      baseReportId: number;
      targetYear: number;
      title: string;
      infoFile: File;
      itemFile: File;
      valueFile: File;
    };

export type UploadState = "idle" | "uploading" | "error";

export function useReportImport(onCompleted: (job: ReportImportJob) => void) {
  const [uploadState, setUploadState] = useState<UploadState>("idle");

  const upload = useCallback(
    async (submission: UploadSubmission) => {
      setUploadState("uploading");
      try {
        if (submission.mode === "completed_report_new") {
          const queued = await uploadReport(submission.file, {
            year: submission.targetYear,
            title: submission.title,
            mode: submission.mode,
            baseReportId: submission.baseReportId,
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
          });
          window.alert(
            [
              `${submission.targetYear}년 연보를 생성했습니다.`,
              `원장 값: 신규 ${result.inserted_values.toLocaleString()}건 · 갱신 ${result.updated_values.toLocaleString()}건 · 동일 ${result.unchanged_values.toLocaleString()}건`,
              `표 생성: 완료 ${result.generated_table_count.toLocaleString()}개 · 확인 필요 ${result.review_table_count.toLocaleString()}개`,
              "기준 연보 스냅샷과 저장된 갱신 정책만 사용했습니다.",
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
            source_file_name: "통계 원장 엑셀",
            status: "completed",
            current_stage: "source_data_import",
            progress_percent: 100,
            attempt_count: 1,
            error_message: "",
          });
        }
        setUploadState("idle");
      } catch (error) {
        setUploadState("error");
        window.alert(error instanceof Error ? error.message : "연보 처리 중 오류가 발생했습니다.");
      }
    },
    [onCompleted],
  );

  return { upload, uploadState };
}
