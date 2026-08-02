import { useLayoutEffect, useRef } from "react";
import { Search, SlidersHorizontal } from "lucide-react";

import type { StatTableSummary, TableStatus } from "../types";
import { groupedValidationIssueCount } from "../utils/validationGrouping";
import { StatusBadge } from "./StatusBadge";

interface TableListProps {
  tables: StatTableSummary[];
  isTestReport: boolean;
  activeTableId: string;
  query: string;
  filter: TableStatus | "all" | "has_issues";
  scrollTop: number;
  onQueryChange: (query: string) => void;
  onFilterChange: (filter: TableStatus | "all" | "has_issues") => void;
  onSelect: (tableId: string) => void;
  onOpen: (tableId: string) => void;
  onScrollTopChange: (scrollTop: number) => void;
}

const filterOptions: Array<{ value: TableStatus | "all" | "has_issues"; label: string }> = [
  { value: "all", label: "전체" },
  { value: "normal", label: "정상" },
  { value: "needs_review", label: "확인 필요" },
  { value: "suspected_error", label: "오류 의심" },
  { value: "has_issues", label: "검수 항목" },
];

export function TableList({
  tables,
  isTestReport,
  activeTableId,
  query,
  filter,
  scrollTop,
  onQueryChange,
  onFilterChange,
  onSelect,
  onOpen,
  onScrollTopChange,
}: TableListProps) {
  const bodyRef = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    const body = bodyRef.current;
    if (!body) {
      return;
    }

    body.scrollTop = scrollTop;
  }, [scrollTop, tables.length]);

  return (
    <aside className="table-list-panel" aria-label="표 목록">
      <div className="panel-toolbar">
        <div className="search-field">
          <Search aria-hidden="true" size={16} />
          <input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="표명, 코드 검색"
          />
        </div>
        <div className="filter-field">
          <SlidersHorizontal aria-hidden="true" size={16} />
          <select
            value={filter}
            onChange={(event) =>
              onFilterChange(event.target.value as TableStatus | "all" | "has_issues")
            }
          >
            {filterOptions.map((option) => (
              <option value={option.value} key={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className={`list-table${isTestReport ? " is-test-report" : ""}`}>
        <div className="list-table__header">
          <span>상태</span>
          <span>표명</span>
          <span>{isTestReport ? "갱신 방식" : "확인"}</span>
          <span>{isTestReport ? "문제" : "오류"}</span>
        </div>
        <div
          className="list-table__body"
          ref={bodyRef}
          onScroll={(event) => onScrollTopChange(event.currentTarget.scrollTop)}
        >
          {tables.map((table) => {
            const reviewCount = groupedValidationIssueCount(table.checks, "확인 필요");
            const criticalCount = groupedValidationIssueCount(table.checks, "오류 의심");

            return (
              <button
                className={`list-row ${activeTableId === table.id ? "is-active" : ""}`}
                key={table.id}
                type="button"
                onClick={() => onSelect(table.id)}
                onDoubleClick={() => onOpen(table.id)}
              >
                <StatusBadge status={table.status} label={table.status_label} />
                <span className="list-row__title">
                  <span className="list-row__name">
                    <small>{table.code}</small>
                    <strong>{table.title}</strong>
                    {table.part_count > 0 ? <em>하위 표 {table.part_count}개</em> : null}
                    {isTestReport && table.generation_message ? (
                      <em className="generation-note">{table.generation_message}</em>
                    ) : null}
                  </span>
                </span>
                {isTestReport ? (
                  <>
                    <span className="generation-mode-cell">
                      {updateModeLabel(table.update_mode)}
                    </span>
                    <span className="generation-problem-cell">
                      {table.status === "normal" ? "-" : "확인"}
                    </span>
                  </>
                ) : (
                  <>
                    <span className="count-cell">{reviewCount}</span>
                    <span className="count-cell">{criticalCount}</span>
                  </>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </aside>
  );
}

function updateModeLabel(mode?: string) {
  const labels: Record<string, string> = {
    rolling_window: "최근 N개년",
    full_snapshot: "전체 교체",
    text_snapshot: "텍스트 교체",
    carry_forward: "이전 값 승계",
    static: "고정",
    mixed: "복합",
  };
  return labels[mode ?? ""] ?? "확인 중";
}
