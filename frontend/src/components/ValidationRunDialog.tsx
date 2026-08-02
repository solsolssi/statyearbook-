import { useMemo, useState } from "react";
import { CheckCircle2, LoaderCircle, X } from "lucide-react";

import type { ValidationCatalogItem } from "../types";

interface ValidationRunDialogProps {
  reportTitle: string;
  catalog: ValidationCatalogItem[];
  state: "idle" | "running" | "error";
  onClose: () => void;
  onRun: (options: {
    selectedRuleKeys: string[];
    reuseExisting: boolean;
    includeLlm: boolean;
  }) => Promise<boolean>;
}

export function ValidationRunDialog({
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
  const isRunning = state === "running";
  const languageReviewSelected =
    selectedKeys.has("spelling") || selectedKeys.has("translation");

  function toggle(key: string) {
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
            onClick={() => setSelectedKeys(new Set(orderedCatalog.map((item) => item.key)))}
          >
            전체 선택
          </button>
          <button type="button" onClick={() => setSelectedKeys(new Set())}>
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
                같은 연도 또는 기준 연보에서 표 구조와 셀 값이 완전히 같은 표만 공유합니다.
              </small>
            </span>
          </label>
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
