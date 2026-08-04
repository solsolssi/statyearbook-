import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, LoaderCircle, X } from "lucide-react";

import { fetchValidationReuseRuns } from "../api/reportApi";
import type { ValidationCatalogItem, ValidationReuseRunOption } from "../types";

interface ValidationRunDialogProps {
  reportId: number;
  reportTitle: string;
  catalog: ValidationCatalogItem[];
  state: "idle" | "running" | "error";
  onClose: () => void;
  onRun: (options: {
    selectedRuleKeys: string[];
    reuseExisting: boolean;
    includeLlm: boolean;
    sourceValidationRunId?: number;
  }) => Promise<boolean>;
}

export function ValidationRunDialog({
  reportId,
  reportTitle,
  catalog,
  state,
  onClose,
  onRun,
}: ValidationRunDialogProps) {
  const orderedCatalog = useMemo(
    () => [...catalog].sort((left, right) => left.order - right.order),
    [catalog],
  );
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(
    () => new Set(orderedCatalog.map((item) => item.key)),
  );
  const [reuseExisting, setReuseExisting] = useState(true);
  const [includeLlm, setIncludeLlm] = useState(false);
  const [reuseRuns, setReuseRuns] = useState<ValidationReuseRunOption[]>([]);
  const [reuseRunsState, setReuseRunsState] = useState<"loading" | "ready" | "error">("loading");
  const [sourceRunId, setSourceRunId] = useState("");
  const [selectionTouched, setSelectionTouched] = useState(false);
  const isRunning = state === "running";
  const languageReviewSelected =
    selectedKeys.has("spelling") || selectedKeys.has("translation");
  const selectedRuleKeys = useMemo(
    () => orderedCatalog
      .map((item) => item.key)
      .filter((key) => selectedKeys.has(key)),
    [orderedCatalog, selectedKeys],
  );
  const reusableRunOptions = reuseRuns;
  const compatibleReuseRuns = useMemo(
    () => reusableRunOptions.filter((run) =>
      selectedRuleKeys.every((key) => run.selected_rule_keys.includes(key)),
    ),
    [reusableRunOptions, selectedRuleKeys],
  );
  const selectedSourceRunId = Number(sourceRunId) || undefined;
  const selectedReuseRun = reusableRunOptions.find(
    (run) => run.id === selectedSourceRunId,
  );
  const selectedReuseRunSummary = selectedReuseRun
    ? `정상 ${selectedReuseRun.normal_count.toLocaleString()}개 표 · 확인 필요 ${selectedReuseRun.needs_review_count.toLocaleString()}개 표 · 오류 의심 ${selectedReuseRun.suspected_error_count.toLocaleString()}개 표`
    : "";

  useEffect(() => {
    let active = true;
    void fetchValidationReuseRuns(reportId)
      .then((runs) => {
        if (active) {
          setReuseRuns(runs);
          const currentReportRun = runs.find((run) => run.report_id === reportId);
          if (currentReportRun && !selectionTouched) {
            setSelectedKeys(new Set(currentReportRun.selected_rule_keys));
          }
          const compatibleRuns = runs.filter((run) => {
            const keys = currentReportRun && !selectionTouched
              ? currentReportRun.selected_rule_keys
              : selectedRuleKeys;
            return keys.every((key) => run.selected_rule_keys.includes(key));
          });
          const firstCompatibleRun = compatibleRuns.find((run) => run.report_id === reportId) ?? compatibleRuns[0];
          setSourceRunId(firstCompatibleRun ? String(firstCompatibleRun.id) : "");
          setReuseRunsState("ready");
        }
      })
      .catch(() => {
        if (active) {
          setReuseRunsState("error");
        }
      });
    return () => {
      active = false;
    };
  }, [reportId]);

  useEffect(() => {
    if (
      selectedSourceRunId &&
      !reusableRunOptions.some((run) => run.id === selectedSourceRunId)
    ) {
      setSourceRunId("");
    }
  }, [reusableRunOptions, selectedSourceRunId]);

  useEffect(() => {
    if (reuseRunsState !== "ready") {
      return;
    }
    const selectedRunIsCompatible =
      selectedReuseRun &&
      selectedRuleKeys.every((key) => selectedReuseRun.selected_rule_keys.includes(key));
    if (selectedRunIsCompatible) {
      return;
    }
    const nextRun =
      compatibleReuseRuns.find((run) => run.report_id === reportId) ??
      compatibleReuseRuns[0];
    setSourceRunId(nextRun ? String(nextRun.id) : "");
  }, [
    compatibleReuseRuns,
    reportId,
    reuseRunsState,
    selectedReuseRun,
    selectedRuleKeys,
  ]);

  function toggle(key: string) {
    setSelectionTouched(true);
    setSelectedKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  async function submit() {
    if (selectedKeys.size === 0 || isRunning) {
      return;
    }
    const completed = await onRun({
      selectedRuleKeys: orderedCatalog
        .map((item) => item.key)
        .filter((key) => selectedKeys.has(key)),
      reuseExisting,
      includeLlm: includeLlm && languageReviewSelected,
      sourceValidationRunId: reuseExisting ? selectedSourceRunId : undefined,
    });
    if (completed) {
      onClose();
    }
  }

  return (
    <div className="upload-dialog-backdrop" role="presentation">
      <section
        className="upload-dialog validation-run-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="validation-run-title"
      >
        <div className="upload-dialog__header">
          <div>
            <span className="section-label">선택 연보 검수</span>
            <h2 id="validation-run-title">검수 항목 선택</h2>
            <p>{reportTitle}</p>
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

        <div className="validation-run-dialog__toolbar">
          <button
            type="button"
            onClick={() => {
              setSelectionTouched(true);
              setSelectedKeys(new Set(orderedCatalog.map((item) => item.key)));
            }}
          >
            전체 선택
          </button>
          <button type="button" onClick={() => {
            setSelectionTouched(true);
            setSelectedKeys(new Set());
          }}>
            전체 해제
          </button>
          <span>{selectedKeys.size}/{orderedCatalog.length}개 선택</span>
        </div>

        <div className="validation-run-option-list">
          {orderedCatalog.map((item) => (
            <label key={item.key}>
              <input
                type="checkbox"
                checked={selectedKeys.has(item.key)}
                onChange={() => toggle(item.key)}
              />
              <span>
                <strong>{item.label}</strong>
                <small>{item.description}</small>
              </span>
            </label>
          ))}
        </div>

        <div className="validation-run-settings">
          <label>
            <input
              type="checkbox"
              checked={reuseExisting}
              onChange={(event) => setReuseExisting(event.target.checked)}
            />
            <span>
              <strong>기존 검수 결과 재사용</strong>
              <small>
                기준 연보 계보 또는 아래에서 고른 검수 실행에서, 표 구조와 셀 값이 완전히 같은 표만 재사용합니다.
              </small>
            </span>
          </label>
          <div className="validation-run-source">
            <label htmlFor="validation-reuse-run">
              <span>
                <strong>재사용할 검수 실행</strong>
                <small>
                  선택하지 않으면 기준 연보 계보에서 자동으로 찾습니다. 선택한 실행에 없는 검수 항목은 재사용하지 않습니다.
                </small>
              </span>
            </label>
            <select
              id="validation-reuse-run"
              aria-label="재사용할 검수 실행"
              disabled={!reuseExisting || isRunning || reuseRunsState === "loading"}
              value={sourceRunId}
              onChange={(event) => setSourceRunId(event.target.value)}
            >
                <option value="">기준 연보 계보에서 자동 선택</option>
                {reusableRunOptions.map((run) => {
                  const missingKeys = selectedRuleKeys.filter((key) => !run.selected_rule_keys.includes(key));
                  return (
                  <option key={run.id} value={run.id} disabled={missingKeys.length > 0}>
                    {run.report_year}년 · {run.report_title}
                    {run.report_id === reportId ? " (현재 연보)" : ""} · {run.completed_at} · 정상 {run.normal_count.toLocaleString()}개 표 · 확인 필요 {run.needs_review_count.toLocaleString()}개 표 · 오류 의심 {run.suspected_error_count.toLocaleString()}개 표
                    {missingKeys.length > 0 ? ` · 미포함: ${missingKeys.join(", ")}` : ""}
                  </option>
                  );
                })}
            </select>
            <small className="validation-run-source__hint">
              {selectedReuseRun
                ? `재사용 원본 검수 항목: ${selectedReuseRun.selected_rule_keys.join(", ")} · ${selectedReuseRunSummary}`
                : reuseRunsState === "loading"
                ? "검수 실행 목록을 불러오는 중입니다."
                : reuseRunsState === "error"
                  ? "목록을 불러오지 못해 기준 연보 계보 재사용만 사용할 수 있습니다."
                  : reusableRunOptions.length === 0
                    ? "재사용할 수 있는 검수 실행이 없습니다."
                    : `표시된 실행 ${reusableRunOptions.length}건`}
            </small>
          </div>
          <label>
            <input
              type="checkbox"
              checked={includeLlm && languageReviewSelected}
              disabled={!languageReviewSelected}
              onChange={(event) => setIncludeLlm(event.target.checked)}
            />
            <span>
              <strong>언어 후보 LLM 자동 판정</strong>
              <small>선택하지 않으면 오탈자·번역 후보를 담당자 확인 대기로 남깁니다.</small>
            </span>
          </label>
        </div>

        <div className="upload-dialog__footer">
          <button
            type="button"
            className="secondary-button"
            disabled={isRunning}
            onClick={onClose}
          >
            취소
          </button>
          <button
            type="button"
            className="primary-button"
            disabled={selectedKeys.size === 0 || isRunning}
            onClick={() => void submit()}
          >
            {isRunning ? (
              <>
                <LoaderCircle className="is-spinning" aria-hidden="true" size={17} />
                검수 중
              </>
            ) : (
              <>
                <CheckCircle2 aria-hidden="true" size={17} />
                선택 항목 검수
              </>
            )}
          </button>
        </div>
      </section>
    </div>
  );
}
