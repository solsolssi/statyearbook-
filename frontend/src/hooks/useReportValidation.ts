import { useCallback, useRef, useState } from "react";

import {
  createValidationJob,
  fetchValidationJob,
  stopValidationJob,
  type ValidationJob,
  type ValidationRunResult,
} from "../api/reportApi";

export type ValidationRunState = "idle" | "running" | "error";

export function useReportValidation(
  onCompleted: (result: ValidationRunResult) => void,
) {
  const [validationRunState, setValidationRunState] =
    useState<ValidationRunState>("idle");
  const [validationJob, setValidationJob] = useState<ValidationJob | null>(null);
  const pollingRef = useRef<number | null>(null);

  const clearPolling = useCallback(() => {
    if (pollingRef.current !== null) window.clearInterval(pollingRef.current);
    pollingRef.current = null;
  }, []);

  const runValidation = useCallback(
    async (
      reportId: number,
      options: {
        selectedRuleKeys: string[];
        reuseExisting: boolean;
        includeProfileLlm: boolean;
        includeLanguageLlm: boolean;
        sourceValidationRunId?: number;
      },
    ) => {
      setValidationRunState("running");
      try {
        const job = await createValidationJob(reportId, options);
        setValidationJob(job);
        pollingRef.current = window.setInterval(() => {
          void fetchValidationJob(job.id).then((updated) => {
            setValidationJob(updated);
            if (["completed", "stopped", "failed"].includes(updated.status)) {
              clearPolling();
              setValidationRunState(updated.status === "failed" ? "error" : "idle");
              if (updated.status === "completed" && updated.result) onCompleted(updated.result);
              if (updated.status === "failed") window.alert(updated.error_message || "연보 검수 중 오류가 발생했습니다.");
            }
          }).catch(() => undefined);
        }, 800);
        return true;
      } catch (error) {
        setValidationRunState("error");
        window.alert(
          error instanceof Error
            ? error.message
            : "연보 검수 중 오류가 발생했습니다.",
        );
        return false;
      }
    },
    [clearPolling, onCompleted],
  );

  const stopValidation = useCallback(async () => {
    if (!validationJob || ["completed", "stopped", "failed"].includes(validationJob.status)) return;
    setValidationJob(await stopValidationJob(validationJob.id));
  }, [validationJob]);

  return { runValidation, stopValidation, validationRunState, validationJob };
}
