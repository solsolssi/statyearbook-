import { useCallback, useState } from "react";

import {
  runReportValidation,
  type ValidationRunResult,
} from "../api/reportApi";

export type ValidationRunState = "idle" | "running" | "error";

export function useReportValidation(
  onCompleted: (result: ValidationRunResult) => void,
) {
  const [validationRunState, setValidationRunState] =
    useState<ValidationRunState>("idle");

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
        const result = await runReportValidation(reportId, options);
        onCompleted(result);
        setValidationRunState("idle");
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
    [onCompleted],
  );

  return { runValidation, validationRunState };
}
