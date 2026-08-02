import { useEffect, useMemo, useState } from "react";
import { LoaderCircle, Play, Search, Workflow } from "lucide-react";

import {
  fetchYearbookReproduction,
  runYearbookReproduction,
} from "../api/reportApi";
import type {
  ReproductionTableAnalysis,
  YearbookReproductionOverview,
} from "../types";

type LoadState = "loading" | "ready" | "error";
type ReproductionFilter = "all" | "mapped" | "review" | "custom";

export function YearbookReproductionPage() {
  const [overview, setOverview] = useState<YearbookReproductionOverview | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<ReproductionFilter>("all");
  const [isBuilding, setIsBuilding] = useState(false);

  useEffect(() => {
    void loadOverview({ reportYear: 2025 });
  }, []);

  const filteredTables = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return (overview?.tables ?? []).filter((table) => {
      const matchesQuery =
        !normalized ||
        [
          table.code,
          table.title,
          table.source_external_id,
          table.source_title,
          ...table.candidates.flatMap((candidate) => [
            candidate.external_id,
            candidate.title,
          ]),
        ]
          .join(" ")
          .toLowerCase()
          .includes(normalized);
      const matchesFilter =
        filter === "all" ||
        (filter === "mapped" && table.mapping_status === "mapped") ||
        (filter === "review" && table.mapping_status !== "mapped") ||
        (filter === "custom" && table.generation_status === "custom_recipe");
      return matchesQuery && matchesFilter;
    });
  }, [filter, overview, query]);

  async function loadOverview(options: { reportId?: string; reportYear?: number }) {
    setLoadState("loading");
    try {
      const payload = await fetchYearbookReproduction(options);
      setOverview(payload);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }

  async function runComparison() {
    if (!overview || isBuilding) {
      return;
    }
    setIsBuilding(true);
    try {
      await runYearbookReproduction(overview.report_id);
      await loadOverview({ reportId: String(overview.report_id) });
    } catch {
      window.alert("연보 셀 재현 비교를 실행하지 못했습니다.");
    } finally {
      setIsBuilding(false);
    }
  }

  if (loadState === "loading") {
    return <div className="state-page">연보와 통계 원장을 대조하는 중입니다.</div>;
  }
  if (loadState === "error" || !overview) {
    return (
      <div className="state-page state-page--error">
        연보 재현 준비 상태를 불러오지 못했습니다.
      </div>
    );
  }

  return (
    <section className="reproduction-workspace">
      <header className="reproduction-summary">
        <div>
          <span className="reproduction-summary__eyebrow">
            <Workflow aria-hidden="true" size={16} />
            원장 → 연보 생성 준비
          </span>
          <h1>{overview.report_year} 연보 재현</h1>
          <p>
            기존 연보는 그대로 보존하고, {overview.target_data_period}년까지의 원장으로
            별도 staging 연보를 만들기 위한 연결 규칙을 점검합니다.
          </p>
        </div>
        <dl className="reproduction-summary__metrics">
          <Metric label="전체 표" value={overview.summary.total_tables} />
          <Metric label="원장 연결" value={overview.summary.mapped_tables} tone="good" />
          <Metric
            label="연결 확인 필요"
            value={overview.summary.review_tables + overview.summary.unmapped_tables}
            tone="warn"
          />
          <Metric
            label="기본 규칙 후보"
            value={overview.summary.basic_recipe_candidates}
            tone="info"
          />
        </dl>
      </header>

      <div className="reproduction-toolbar">
        <label>
          <span>기준 연보</span>
          <select
            value={String(overview.report_id)}
            onChange={(event) => void loadOverview({ reportId: event.target.value })}
          >
            {overview.available_reports.map((report) => (
              <option key={report.id} value={report.id}>
                {report.year} · {report.title}
                {report.is_archived ? " (보관)" : ""}
              </option>
            ))}
          </select>
        </label>
        <div className="search-field reproduction-search">
          <Search aria-hidden="true" size={16} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="표 코드, 표명, 원장 ID 검색"
          />
        </div>
        <div className="reproduction-filters" aria-label="재현 준비 필터">
          <FilterButton active={filter === "all"} onClick={() => setFilter("all")}>
            전체
          </FilterButton>
          <FilterButton active={filter === "mapped"} onClick={() => setFilter("mapped")}>
            연결됨
          </FilterButton>
          <FilterButton active={filter === "review"} onClick={() => setFilter("review")}>
            확인 필요
          </FilterButton>
          <FilterButton active={filter === "custom"} onClick={() => setFilter("custom")}>
            개별 규칙
          </FilterButton>
        </div>
        <button
          className="reproduction-run-button"
          type="button"
          disabled={isBuilding}
          onClick={() => void runComparison()}
        >
          {isBuilding ? (
            <LoaderCircle className="is-spinning" aria-hidden="true" size={16} />
          ) : (
            <Play aria-hidden="true" size={16} />
          )}
          {isBuilding ? "비교 중" : "셀 재현 비교 실행"}
        </button>
      </div>

      <div
        className={`reproduction-build-summary${
          overview.latest_build ? "" : " is-empty"
        }`}
      >
        {overview.latest_build ? (
          <>
            <strong>최근 dry-run #{overview.latest_build.id}</strong>
            <span className="is-exact">
              완전 일치 {overview.latest_build.exact_tables.toLocaleString()}표
            </span>
            <span className="is-source-difference">
              원장값 반영{" "}
              {(
                overview.latest_build.source_difference_tables ??
                overview.latest_build.mismatch_tables
              ).toLocaleString()}
              표 ·{" "}
              {(
                overview.latest_build.source_difference_cells ??
                overview.latest_build.mismatch_cells
              ).toLocaleString()}
              셀
            </span>
            <span>
              구조 변환 필요{" "}
              {(
                overview.latest_build.unavailable_tables +
                overview.latest_build.recipe_required_tables
              ).toLocaleString()}
              표
            </span>
            <span>
              원장 기간 없음{" "}
              {overview.latest_build.source_missing_tables.toLocaleString()}표
            </span>
            <span>
              매핑 확인 {overview.latest_build.mapping_review_tables.toLocaleString()}표
            </span>
            <small>{overview.latest_build.completed_at}</small>
          </>
        ) : (
          <span>
            아직 staging 셀 비교를 실행하지 않았습니다. 기존 연보와 검수 결과는 변경되지
            않습니다.
          </span>
        )}
      </div>

      <div className="reproduction-list">
        <div className="reproduction-list__caption">
          <strong>{filteredTables.length.toLocaleString()}개 표</strong>
          <span>
            초안 레시피 {overview.summary.draft_recipes.toLocaleString()}개 ·{" "}
            {overview.latest_build ? "최근 dry-run 결과 표시 중" : "실제 셀 재현 비교 전"}
          </span>
        </div>
        <div className="reproduction-list__header" aria-hidden="true">
          <span>연보 표</span>
          <span>원장 연결</span>
          <span>표시 기간</span>
          <span>생성 규칙</span>
          <span>상태</span>
        </div>
        <div className="reproduction-list__body">
          {filteredTables.map((table) => (
            <ReproductionRow table={table} key={table.table_id} />
          ))}
        </div>
      </div>
    </section>
  );
}

function Metric({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number;
  tone?: "default" | "good" | "warn" | "info";
}) {
  return (
    <div data-tone={tone}>
      <dt>{label}</dt>
      <dd>{value.toLocaleString()}</dd>
    </div>
  );
}

function FilterButton({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: string;
  onClick: () => void;
}) {
  return (
    <button className={active ? "is-active" : ""} type="button" onClick={onClick}>
      {children}
    </button>
  );
}

function ReproductionRow({ table }: { table: ReproductionTableAnalysis }) {
  const candidateText =
    table.mapping_status === "mapped"
      ? `${table.source_external_id} · ${table.source_title}`
      : table.candidates.length > 0
        ? `후보 ${table.candidates.length}개 · ${table.candidates
            .map((candidate) => candidate.title)
            .join(", ")}`
        : "연결 후보 없음";
  return (
    <article className="reproduction-row">
      <div className="reproduction-row__table">
        <small>{table.code}</small>
        <strong>{table.title}</strong>
      </div>
      <div className="reproduction-row__source">
        <strong>{candidateText}</strong>
        <small>{table.reason}</small>
      </div>
      <div>
        <strong>{periodRuleLabel(table)}</strong>
        <small>기준 {table.period_rule.target_period}년</small>
      </div>
      <div>
        <strong>{materializerLabel(table.materializer)}</strong>
        <small>{table.recipe_status === "draft" ? "초안 저장됨" : "초안 저장 전"}</small>
      </div>
      <div>
        <span
          className={`reproduction-status is-${
            table.comparison_status || table.mapping_status
          }`}
        >
          {table.comparison_status
            ? comparisonStatusLabel(table.comparison_status)
            : mappingStatusLabel(table.mapping_status)}
        </span>
        {table.comparison_status === "source_difference" ? (
          <small>
            기존 연보와 {table.mismatch_count.toLocaleString()}셀 차이 · 원장값 사용
          </small>
        ) : table.comparison_status === "mismatch" ? (
          <small>{table.mismatch_count.toLocaleString()}셀 차이</small>
        ) : table.comparison_error ? (
          <small>{table.comparison_error}</small>
        ) : table.mapping_status === "mapped" ? (
          <small>신뢰도 {Math.round(table.confidence * 100)}%</small>
        ) : null}
      </div>
    </article>
  );
}

function periodRuleLabel(table: ReproductionTableAnalysis) {
  if (table.period_rule.mode === "latest_n") {
    return `최근 ${table.period_rule.count}개년`;
  }
  return "당해 기준시점";
}

function materializerLabel(materializer: string) {
  const labels: Record<string, string> = {
    period_rows: "연도 행 이동",
    period_columns: "연도 열 이동",
    current_period_rows: "당해연도 행 갱신",
    custom: "개별 변환",
  };
  return labels[materializer] ?? materializer;
}

function mappingStatusLabel(status: ReproductionTableAnalysis["mapping_status"]) {
  if (status === "mapped") {
    return "연결됨";
  }
  if (status === "review") {
    return "후보 확인";
  }
  return "미연결";
}

function comparisonStatusLabel(status: string) {
  const labels: Record<string, string> = {
    exact: "완전 일치",
    mismatch: "값 차이",
    source_difference: "원장값 반영",
    carried_forward: "이전 값 승계",
    static: "고정 표 유지",
    empty: "빈 값 유지",
    source_missing: "원장 기간 없음",
    unavailable: "구조 확인",
    recipe_required: "개별 규칙",
    mapping_review: "매핑 확인",
  };
  return labels[status] ?? status;
}
