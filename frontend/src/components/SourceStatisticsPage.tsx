import { useEffect, useMemo, useRef, useState } from "react";
import { Database, Search } from "lucide-react";

import {
  fetchSourceStatistic,
  fetchSourceStatistics,
} from "../api/reportApi";
import type {
  ColumnDefinition,
  SourceStatisticDetail,
  SourceStatisticsOverview,
} from "../types";
import { DataGrid } from "./DataGrid";

type LoadState = "loading" | "ready" | "error";

export function SourceStatisticsPage() {
  const [overview, setOverview] = useState<SourceStatisticsOverview | null>(null);
  const [detail, setDetail] = useState<SourceStatisticDetail | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [overviewState, setOverviewState] = useState<LoadState>("loading");
  const [detailState, setDetailState] = useState<LoadState>("loading");
  const requestKeyRef = useRef("");

  useEffect(() => {
    let active = true;
    void fetchSourceStatistics()
      .then((payload) => {
        if (!active) {
          return;
        }
        setOverview(payload);
        setOverviewState("ready");
        const initial =
          payload.datasets.find((dataset) => dataset.value_count > 0) ?? payload.datasets[0];
        setSelectedId((current) => current || initial?.external_id || "");
      })
      .catch(() => {
        if (active) {
          setOverviewState("error");
        }
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDetailState("ready");
      return;
    }
    void loadDetail(selectedId);
  }, [selectedId]);

  const filteredDatasets = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return overview?.datasets ?? [];
    }
    return (overview?.datasets ?? []).filter((dataset) =>
      [
        dataset.external_id,
        dataset.title,
        dataset.directory,
        dataset.department,
      ]
        .join(" ")
        .toLowerCase()
        .includes(normalized),
    );
  }, [overview, query]);

  const columns = useMemo<ColumnDefinition[]>(
    () =>
      (detail?.columns ?? []).map((column, index) => ({
        key: column.key,
        label: column.label,
        align: column.align,
        width: index === 0 ? "190px" : "140px",
      })),
    [detail],
  );

  async function loadDetail(externalId: string, period?: string) {
    const requestKey = `${externalId}:${period ?? ""}`;
    requestKeyRef.current = requestKey;
    setDetailState("loading");
    try {
      const payload = await fetchSourceStatistic(externalId, period);
      if (requestKeyRef.current !== requestKey) {
        return;
      }
      setDetail(payload);
      setDetailState("ready");
    } catch {
      if (requestKeyRef.current === requestKey) {
        setDetail(null);
        setDetailState("error");
      }
    }
  }

  if (overviewState === "loading") {
    return <div className="state-page">통계 원장을 불러오는 중입니다.</div>;
  }
  if (overviewState === "error" || !overview) {
    return <div className="state-page state-page--error">통계 원장을 불러오지 못했습니다.</div>;
  }

  return (
    <section className="source-workspace">
      <header className="source-summary">
        <div>
          <span className="source-summary__eyebrow">
            <Database aria-hidden="true" size={16} />
            Excel 시계열 원장
          </span>
          <h1>통계 원장</h1>
          <p>기존 통계연보와 분리된 원천 데이터를 기준시점별로 조회합니다.</p>
        </div>
        <dl className="source-summary__metrics">
          <div>
            <dt>전체 통계</dt>
            <dd>{overview.summary.total_datasets.toLocaleString()}</dd>
          </div>
          <div>
            <dt>데이터 보유</dt>
            <dd>{overview.summary.datasets_with_values.toLocaleString()}</dd>
          </div>
          <div>
            <dt>원장 셀</dt>
            <dd>{overview.summary.total_values.toLocaleString()}</dd>
          </div>
          <div>
            <dt>수록 범위</dt>
            <dd>
              {overview.summary.earliest_period || "-"}–{overview.summary.latest_period || "-"}
            </dd>
          </div>
        </dl>
      </header>

      <div className="source-workspace__body">
        <aside className="source-catalog">
          <div className="search-field source-catalog__search">
            <Search aria-hidden="true" size={16} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="통계명, 표 ID, 부서 검색"
            />
          </div>
          <div className="source-catalog__count">
            {filteredDatasets.length.toLocaleString()}개 통계
          </div>
          <div className="source-catalog__list">
            {filteredDatasets.map((dataset) => (
              <button
                className={dataset.external_id === selectedId ? "is-active" : ""}
                key={dataset.external_id}
                type="button"
                onClick={() => setSelectedId(dataset.external_id)}
              >
                <small>{dataset.external_id}</small>
                <strong>{dataset.title}</strong>
                <span>
                  {dataset.latest_period
                    ? `${dataset.earliest_period}–${dataset.latest_period} · ${dataset.period_count}개 시점`
                    : "데이터 없음"}
                </span>
                {dataset.department ? <em>{dataset.department}</em> : null}
              </button>
            ))}
          </div>
        </aside>

        <article className="source-detail">
          {detailState === "loading" ? (
            <div className="source-detail__state">데이터를 불러오는 중입니다.</div>
          ) : null}
          {detailState === "error" ? (
            <div className="source-detail__state source-detail__state--error">
              상세 데이터를 불러오지 못했습니다.
            </div>
          ) : null}
          {detailState === "ready" && detail ? (
            <>
              <div className="source-detail__header">
                <div>
                  <small>{detail.external_id}</small>
                  <h2>{detail.title}</h2>
                  <p>
                    {[detail.metadata.directory, detail.metadata.department]
                      .filter(Boolean)
                      .join(" · ") || "추가 메타정보 없음"}
                  </p>
                </div>
                <label className="source-period-select">
                  <span>기준시점</span>
                  <select
                    value={detail.selected_period}
                    onChange={(event) =>
                      void loadDetail(detail.external_id, event.target.value)
                    }
                  >
                    {detail.periods.map((period) => (
                      <option value={period.value} key={period.value}>
                        {period.label} ({period.row_count.toLocaleString()}행)
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="source-detail__meta">
                <span>항목 {detail.columns.length.toLocaleString()}개</span>
                <span>행 {detail.total_rows.toLocaleString()}개</span>
                {detail.metadata.data_reference_time ? (
                  <span>자료시점 {detail.metadata.data_reference_time}</span>
                ) : null}
                {detail.metadata.input_status ? (
                  <span>입력상태 {detail.metadata.input_status}</span>
                ) : null}
              </div>
              {columns.length > 0 ? (
                <DataGrid
                  columns={columns}
                  rows={detail.rows}
                  theme="green"
                  stickyHeader
                />
              ) : (
                <div className="source-detail__state">선택한 통계에 데이터가 없습니다.</div>
              )}
            </>
          ) : null}
          {detailState === "ready" && !detail ? (
            <div className="source-detail__state">왼쪽에서 통계를 선택해 주세요.</div>
          ) : null}
        </article>
      </div>
    </section>
  );
}
