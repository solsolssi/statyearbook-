import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight, FileCode2 } from "lucide-react";

import type { CheckFilter } from "../../hooks/useValidationSelection";
import type { DisplayCheck } from "../DetailView";

const FILTERS: Array<{ id: CheckFilter; label: string }> = [
  { id: "all", label: "전체" },
  { id: "passed", label: "통과" },
  { id: "review", label: "확인 필요" },
  { id: "error", label: "오류 의심" },
];

interface ValidationResultPanelProps {
  filter: CheckFilter;
  counts: Record<CheckFilter, number>;
  checks: DisplayCheck[];
  selected?: DisplayCheck;
  selectedIndex: number;
  metadataContent?: ReactNode;
  calculationUsage?: ReactNode;
  onFilterChange: (filter: CheckFilter) => void;
  onSelect: (id: string) => void;
  onMove: (direction: -1 | 1) => void;
}

function displayTitle(check: Pick<DisplayCheck, "formula" | "type">) {
  return check.formula?.trim() || check.type;
}

export function ValidationResultPanel({
  filter,
  counts,
  checks,
  selected,
  selectedIndex,
  metadataContent,
  calculationUsage,
  onFilterChange,
  onSelect,
  onMove,
}: ValidationResultPanelProps) {
  return (
    <div className="detail-section check-review-panel">
      <div className="content-title-row">
        <h2>검수 결과</h2>
      </div>

      <div className="check-filter-tabs" aria-label="검수 결과 필터">
        {FILTERS.map((item) => (
          <button
            className={filter === item.id ? "is-active" : ""}
            key={item.id}
            type="button"
            onClick={() => onFilterChange(item.id)}
          >
            <span>{item.label}</span>
            <strong>{counts[item.id]}</strong>
          </button>
        ))}
      </div>

      {checks.length > 0 ? (
        <div className="check-result-list" aria-label="검수 목록">
          {checks.map((check, index) => (
            <button
              className={selected?.id === check.id ? "is-active" : ""}
              key={check.id}
              type="button"
              onClick={() => onSelect(check.id)}
            >
              <span>{index + 1}</span>
              <strong>{displayTitle(check)}</strong>
              <em>{check.status}</em>
            </button>
          ))}
        </div>
      ) : null}

      {selected ? (
        <article className={`check-card check-card--${selected.severity}`}>
          <div className="check-card__headline">
            <div>
              <span>{selected.formula?.trim() ? selected.type : "검수 항목"}</span>
              <h3>{displayTitle(selected)}</h3>
            </div>
            <strong>{selected.status}</strong>
          </div>
          {metadataContent ?? (
            <>
              <dl className="check-card__location">
                <div>
                  <dt>행</dt>
                  <dd>{selected.rowSummary}</dd>
                </div>
                <div>
                  <dt>열</dt>
                  <dd>{selected.columnSummary}</dd>
                </div>
              </dl>
              <dl className="check-card__values">
                <div>
                  <dt>현재값</dt>
                  <dd>{selected.current_value}</dd>
                </div>
                <div>
                  <dt>검수값</dt>
                  <dd>{selected.expected_value ?? "-"}</dd>
                </div>
                <div>
                  <dt>차이</dt>
                  <dd>{selected.difference ?? "-"}</dd>
                </div>
              </dl>
            </>
          )}
          <p>{selected.detail}</p>
          {selected.formula && selected.formula !== displayTitle(selected) ? (
            <div className="formula-box">
              <FileCode2 aria-hidden="true" size={16} />
              <span>{selected.formula}</span>
            </div>
          ) : null}
          {calculationUsage}
        </article>
      ) : (
        <p className="empty-copy">해당 내용이 없습니다.</p>
      )}

      {checks.length > 0 ? (
        <div className="check-card-nav">
          <button
            className="icon-button"
            type="button"
            onClick={() => onMove(-1)}
            disabled={checks.length <= 1}
            aria-label="이전 검수"
          >
            <ChevronLeft aria-hidden="true" size={18} />
          </button>
          <span>{`${selectedIndex + 1} / ${checks.length}`}</span>
          <button
            className="icon-button"
            type="button"
            onClick={() => onMove(1)}
            disabled={checks.length <= 1}
            aria-label="다음 검수"
          >
            <ChevronRight aria-hidden="true" size={18} />
          </button>
        </div>
      ) : null}
    </div>
  );
}
