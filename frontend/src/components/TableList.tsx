import { useLayoutEffect, useRef } from "react";
import { Search, SlidersHorizontal } from "lucide-react";

import type { StatTableSummary, TableStatus } from "../types";
import { groupedValidationIssueCount } from "../utils/validationGrouping";
import { StatusBadge } from "./StatusBadge";
import type { ReportReviewStage } from "../utils/validationVisibility";

interface TableListProps {
  tables: StatTableSummary[];
  reviewStage?: ReportReviewStage;
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
  reviewStage = "validated",
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
            {filterOptions
              .filter((option) =>
                reviewStage === "unvalidated"
                  ? ["all", "normal"].includes(option.value)
                  : reviewStage === "draft"
                    ? ["all", "normal", "needs_review"].includes(option.value)
                    : true,
              )
              .map((option) => (
                <option value={option.value} key={option.value}>
                  {reviewStage !== "validated" && option.value === "normal"
                    ? "검수 전"
                    : option.label}
                </option>
              ))}
          </select>
        </div>
      </div>

      <div className="list-table">
        <div className="list-table__header">
          <span>상태</span>
          <span>표명</span>
          <span>확인</span>
          <span>오류</span>
        </div>
        <div
          className="list-table__body"
          ref={bodyRef}
          onScroll={(event) => onScrollTopChange(event.currentTarget.scrollTop)}
        >
          {tables.map((table) => {
            const validationReviewCount = groupedValidationIssueCount(table.checks, "확인 필요");
            const reviewCount = validationReviewCount || (table.status === "needs_review" ? 1 : 0);
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
                  </span>
                </span>
                <span className="count-cell">{reviewCount}</span>
                <span className="count-cell">{criticalCount}</span>
              </button>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
