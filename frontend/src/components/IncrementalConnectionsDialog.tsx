import { useEffect, useMemo, useState } from "react";
import { GitBranch, LoaderCircle, X } from "lucide-react";

import {
  createStatisticFromIncrement,
  fetchIncrementalConnections,
  ignoreUnmatchedIncrement,
  keepExistingIncrementTable,
} from "../api/reportApi";
import type { IncrementalConnectionOverview } from "../types";

interface IncrementalConnectionsDialogProps {
  reportId: number;
  onClose: () => void;
  onOpenTable: (tableCode: string) => void;
  onCreatedTable?: (tableId: string) => void;
}

const reasonLabels: Record<string, string> = {
  NO_INCREMENT_CANDIDATE: "증분 후보 없음",
  NO_RELIABLE_CANDIDATE: "신뢰할 수 있는 후보 없음",
  AMBIGUOUS_CANDIDATE: "후보가 모호함",
  MISSING_ITEM_METADATA: "표항목 정보 없음",
  UNDESCRIBED_VALUE_ITEMS: "값의 항목 설명 누락",
  HEADER_STRUCTURE_MISMATCH: "헤더 구조 변경",
  ROW_STRUCTURE_MISMATCH: "행 구조 변경",
  ROW_LABEL_MISMATCH: "행 항목 변경",
  NO_TARGET_VALUES: "목표 데이터 없음",
  UNMATCHED_NEW_INCREMENT: "새 통계 또는 미연결 증분",
  STRUCTURE_REBUILT: "증분 구조로 표 재구성 완료",
  STRUCTURE_VERIFIED: "기존 구조에 값 반영 완료",
  YEAR_APPENDED: "새 연도 추가 완료",
  YEAR_ROW_UPDATED: "기존 목표연도 갱신 완료",
  GROUPED_YEAR_ROWS_APPENDED: "새 연도 묶음 행 추가 완료",
  YEAR_COLUMN_APPENDED: "새 연도 열 추가 완료",
  YEAR_COLUMN_UPDATED: "기존 목표연도 열 갱신 완료",
  YEAR_COLUMN_ROW_MISMATCH: "연도 열의 행 항목 연결 확인 필요",
  TARGET_YEAR_MISSING: "증분 기준연도 없음",
  YEAR_SEQUENCE_CONFLICT: "증분 연도 순서 확인 필요",
  REFERENCE_TABLE_AMBIGUOUS: "완성 연보의 대응 표 확인 필요",
  REFERENCE_STRUCTURE_MISMATCH: "완성 연보 대조 결과 구조 불일치",
  REFERENCE_VALUE_MISMATCH: "완성 연보 대조 결과 값 불일치",
  MANUAL_EDIT_REQUIRES_REVIEW: "수정된 표 재확인 필요",
  NEW_INCREMENT_CREATED: "새 증분으로 통계 생성",
};

export function IncrementalConnectionsDialog({
  reportId,
  onClose,
  onOpenTable,
  onCreatedTable,
}: IncrementalConnectionsDialogProps) {
  const [overview, setOverview] = useState<IncrementalConnectionOverview | null>(null);
  const [error, setError] = useState("");
  const [creatingKey, setCreatingKey] = useState("");
  const [resolvingKey, setResolvingKey] = useState("");

  async function reloadConnections() {
    setOverview(await fetchIncrementalConnections(reportId));
  }

  async function handleKeepExisting(tableCode: string) {
    if (!window.confirm(`${tableCode} 통계에는 이번 증분을 적용하지 않고 이전 값을 유지할까요?`)) return;
    setResolvingKey(`table:${tableCode}`);
    try {
      await keepExistingIncrementTable(reportId, tableCode);
      await reloadConnections();
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "기존값 유지 결정을 저장하지 못했습니다.");
    } finally {
      setResolvingKey("");
    }
  }

  async function handleIgnoreIncrement(sourceKey: string) {
    if (!window.confirm(`${sourceKey} 증분을 이번 연보에서 제외할까요? 이 결정은 연결 기록에 남습니다.`)) return;
    setResolvingKey(`increment:${sourceKey}`);
    try {
      await ignoreUnmatchedIncrement(reportId, sourceKey);
      await reloadConnections();
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "증분 제외 결정을 저장하지 못했습니다.");
    } finally {
      setResolvingKey("");
    }
  }

  async function handleCreateStatistic(sourceKey: string, suggestedTitle: string) {
    const tableCode = window.prompt("새 통계의 표 번호를 입력해 주세요.");
    if (!tableCode?.trim()) return;
    const title = window.prompt("새 통계의 제목을 입력해 주세요.", suggestedTitle);
    if (!title?.trim()) return;
    if (!window.confirm(`${tableCode.trim()} ${title.trim()} 통계를 이 증분 구조로 생성할까요?`)) return;
    setCreatingKey(sourceKey);
    try {
      const created = await createStatisticFromIncrement(
        reportId,
        sourceKey,
        tableCode.trim(),
        title.trim(),
      );
      onCreatedTable?.(created.table_id);
      onClose();
    } catch (reason) {
      window.alert(reason instanceof Error ? reason.message : "새 통계를 만들지 못했습니다.");
    } finally {
      setCreatingKey("");
    }
  }

  useEffect(() => {
    let active = true;
    void fetchIncrementalConnections(reportId)
      .then((result) => {
        if (active) setOverview(result);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "증분 연결 현황을 불러오지 못했습니다.");
      });
    return () => {
      active = false;
    };
  }, [reportId]);

  const reviewConnections = useMemo(
    () => overview?.connections.filter((item) => item.generation_status === "mapping_review") ?? [],
    [overview],
  );

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="incremental-connections-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="incremental-connections-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <span>연보 생성</span>
            <h2 id="incremental-connections-title"><GitBranch size={22} /> 증분 연결</h2>
          </div>
          <button type="button" aria-label="닫기" onClick={onClose}><X /></button>
        </header>
        {!overview && !error ? (
          <div className="incremental-connections-loading"><LoaderCircle className="is-spinning" /> 연결 현황을 불러오는 중입니다.</div>
        ) : null}
        {error ? <p className="incremental-connections-error">{error}</p> : null}
        {overview ? (
          <>
            <div className="incremental-connections-summary">
              <span>전체 통계 <strong>{overview.summary.total}</strong></span>
              <span>자동 반영 <strong>{overview.summary.connected}</strong></span>
              <span>확인 필요 <strong>{overview.summary.review}</strong></span>
              <span>미연결 증분 <strong>{overview.summary.unmatched}</strong></span>
              {overview.summary.deleted > 0 ? (
                <span>삭제 반영 <strong>{overview.summary.deleted}</strong></span>
              ) : null}
            </div>
            <div className="incremental-connections-body">
              <section>
                <h3>확인 필요한 기존 통계</h3>
                {reviewConnections.length ? reviewConnections.map((item) => (
                  <article className="incremental-review-item" key={item.table_code}>
                    <button type="button" onClick={() => onOpenTable(item.table_code)}>
                      <span><strong>{item.table_code}</strong> {item.title}</span>
                      <small>{reasonLabels[item.reason_code] || item.reason_code || "연결 확인 필요"}</small>
                      {item.candidates.length ? (
                        <em>추천 {item.candidates[0].source_key} · {Math.round(item.candidates[0].score * 100)}%</em>
                      ) : null}
                      {item.llm_assistance ? (
                        <em>
                          LLM 제안 {Math.round(item.llm_assistance.confidence * 100)}% · {item.llm_assistance.reason}
                        </em>
                      ) : null}
                    </button>
                    <button
                      className="incremental-resolution-button"
                      type="button"
                      disabled={Boolean(resolvingKey)}
                      onClick={() => void handleKeepExisting(item.table_code)}
                    >
                      {resolvingKey === `table:${item.table_code}` ? "처리 중" : "기존값 유지"}
                    </button>
                  </article>
                )) : <p>확인 필요한 기존 통계가 없습니다.</p>}
              </section>
              <section>
                <h3>새 통계 또는 아직 붙지 않은 증분</h3>
                <p className="incremental-connections-hint">
                  기존 통계라면 해당 통계에서 M키를 입력하고, 새 통계라면 수정 화면의 통계 추가로 표를 만든 뒤 M키를 연결하세요.
                </p>
                {overview.unmatched_increments.length ? overview.unmatched_increments.map((item) => (
                  <article key={item.source_key}>
                    <strong>{String(item.evidence.title || item.title || item.source_key)}</strong>
                    <span>{item.source_key}</span>
                    <small>표항목 {String(item.evidence.items ?? 0)}개 · 값 {String(item.evidence.values ?? 0)}개</small>
                    {item.llm_assistance ? (
                      <em>
                        LLM 제안 {Math.round(item.llm_assistance.confidence * 100)}% · {item.llm_assistance.reason}
                      </em>
                    ) : null}
                    {Number(item.evidence.items ?? 0) > 0 && Number(item.evidence.values ?? 0) > 0 ? (
                      <div className="incremental-item-actions">
                        <button
                          type="button"
                          disabled={Boolean(creatingKey || resolvingKey)}
                          onClick={() => void handleCreateStatistic(
                            item.source_key,
                            String(item.evidence.title || item.title || item.source_key),
                          )}
                        >
                          {creatingKey === item.source_key ? "생성 중" : "새 통계로 추가"}
                        </button>
                        <button
                          type="button"
                          disabled={Boolean(creatingKey || resolvingKey)}
                          onClick={() => void handleIgnoreIncrement(item.source_key)}
                        >
                          {resolvingKey === `increment:${item.source_key}` ? "처리 중" : "이번 연보에서 제외"}
                        </button>
                      </div>
                    ) : <em>표항목 파일 보완 필요</em>}
                    {Number(item.evidence.items ?? 0) <= 0 || Number(item.evidence.values ?? 0) <= 0 ? (
                      <button
                        type="button"
                        disabled={Boolean(resolvingKey)}
                        onClick={() => void handleIgnoreIncrement(item.source_key)}
                      >
                        {resolvingKey === `increment:${item.source_key}` ? "처리 중" : "이번 연보에서 제외"}
                      </button>
                    ) : null}
                  </article>
                )) : <p>남은 미연결 증분이 없습니다.</p>}
                {overview.ignored_increments.length ? (
                  <small>이번 연보에서 제외하도록 확인한 증분 {overview.ignored_increments.length}개</small>
                ) : null}
              </section>
            </div>
          </>
        ) : null}
      </section>
    </div>
  );
}
