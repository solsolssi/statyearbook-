import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Check, KeyRound, LoaderCircle, Search, ShieldCheck } from "lucide-react";

import { fetchReportEditAccess, saveReportEditPassword } from "../api/reportApi";
import type { ReportEditAccess, ReportOption, StatisticEditAccess } from "../types";

interface PasswordSettingsPageProps {
  reportId: number;
  availableReports: ReportOption[];
  onReportChange: (reportId: string) => void;
}

export function PasswordSettingsPage({
  reportId,
  availableReports,
  onReportChange,
}: PasswordSettingsPageProps) {
  const [access, setAccess] = useState<ReportEditAccess | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [editingTableId, setEditingTableId] = useState("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    let active = true;
    setStatus("loading");
    setEditingTableId("");
    setQuery("");
    void fetchReportEditAccess(reportId)
      .then((result) => {
        if (active) {
          setAccess(result);
          setStatus("ready");
        }
      })
      .catch(() => {
        if (active) {
          setStatus("error");
        }
      });
    return () => {
      active = false;
    };
  }, [reportId]);

  const visibleStatistics = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return access?.statistics ?? [];
    }
    return (access?.statistics ?? []).filter((statistic) =>
      [statistic.code, statistic.title, statistic.source_officer]
        .join(" ")
        .toLowerCase()
        .includes(normalized),
    );
  }, [access, query]);

  return (
    <section className="password-settings-page">
      <header className="password-settings-hero">
        <div>
          <span className="section-label">
            <ShieldCheck aria-hidden="true" size={16} />
            통계별 수정 보호
          </span>
          <h1>통계 수정 비밀번호</h1>
          <p>
            같은 연보 안에서도 통계마다 비밀번호가 따로 관리됩니다. 초기 비밀번호는
            담당 주무관 유선번호의 마지막 네 자리이며, 번호가 없으면 0000입니다.
          </p>
        </div>
        <div className="password-settings-report-select">
          <label>
            <span>대상 연보</span>
            <select
              value={String(reportId)}
              onChange={(event) => onReportChange(event.target.value)}
            >
              {availableReports
                .filter((report) => report.kind !== "test")
                .map((report) => (
                  <option key={report.id} value={report.id}>
                    {report.year} · {report.title}
                  </option>
                ))}
            </select>
          </label>
        </div>
      </header>

      {status === "loading" ? (
        <div className="password-settings-state">
          <LoaderCircle className="is-spinning" aria-hidden="true" size={20} />
          통계별 비밀번호 설정을 불러오는 중입니다.
        </div>
      ) : status === "error" || !access ? (
        <div className="password-settings-state is-error">
          비밀번호 설정을 불러오지 못했습니다.
        </div>
      ) : (
        <>
          <div className="password-settings-toolbar">
            <div>
              <strong>{access.year}년 연보</strong>
              <span>{access.statistics.length.toLocaleString()}개 통계</span>
            </div>
            <label className="password-settings-search">
              <Search aria-hidden="true" size={17} />
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="통계 번호, 제목, 담당자 검색"
              />
            </label>
          </div>
          <div className="statistic-password-list">
            {visibleStatistics.map((statistic) => (
              <article className="report-password-card" key={statistic.table_id}>
                <div className="report-password-card__identity">
                  <small>{statistic.code}</small>
                  <strong>{statistic.title}</strong>
                  <p>{statistic.source_officer || "담당 주무관 정보 없음"}</p>
                </div>
                <div className="report-password-card__status">
                  <span className="access-badge is-set">
                    {statistic.is_initial_password ? (
                      <KeyRound aria-hidden="true" size={14} />
                    ) : (
                      <Check aria-hidden="true" size={14} />
                    )}
                    {statistic.is_initial_password ? "초기 비밀번호" : "변경됨"}
                  </span>
                  {statistic.updated_at ? <small>최근 설정 {statistic.updated_at}</small> : null}
                </div>
                <button
                  className="secondary-button"
                  type="button"
                  onClick={() => setEditingTableId(statistic.table_id)}
                >
                  비밀번호 변경
                </button>
                {editingTableId === statistic.table_id ? (
                  <PasswordForm
                    statistic={statistic}
                    reportId={reportId}
                    onCancel={() => setEditingTableId("")}
                    onSaved={(saved) => {
                      setAccess(saved);
                      setEditingTableId("");
                    }}
                  />
                ) : null}
              </article>
            ))}
            {visibleStatistics.length === 0 ? (
              <div className="password-settings-state">검색 결과가 없습니다.</div>
            ) : null}
          </div>
        </>
      )}
    </section>
  );
}

function PasswordForm({
  statistic,
  reportId,
  onCancel,
  onSaved,
}: {
  statistic: StatisticEditAccess;
  reportId: number;
  onCancel: () => void;
  onSaved: (access: ReportEditAccess) => void;
}) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const canSave =
    Boolean(currentPassword) && newPassword.length >= 4 && newPassword === confirmation;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSave || saving) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      onSaved(
        await saveReportEditPassword(reportId, statistic.table_id, {
          currentPassword,
          newPassword,
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "비밀번호를 저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="password-setting-form" onSubmit={(event) => void submit(event)}>
      <label>
        <span>현재 비밀번호</span>
        <input
          autoFocus
          type="password"
          value={currentPassword}
          onChange={(event) => setCurrentPassword(event.target.value)}
          placeholder={statistic.is_initial_password ? "유선번호 뒷자리 4자리 또는 0000" : "현재 비밀번호"}
        />
      </label>
      <label>
        <span>새 비밀번호</span>
        <input
          type="password"
          minLength={4}
          value={newPassword}
          onChange={(event) => setNewPassword(event.target.value)}
          placeholder="4자 이상"
        />
      </label>
      <label>
        <span>새 비밀번호 확인</span>
        <input
          type="password"
          minLength={4}
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
        />
      </label>
      {confirmation && newPassword !== confirmation ? (
        <p className="form-error">새 비밀번호가 서로 다릅니다.</p>
      ) : null}
      {error ? <p className="form-error">{error}</p> : null}
      <div className="password-setting-form__actions">
        <button className="secondary-button" type="button" onClick={onCancel}>취소</button>
        <button className="primary-button" type="submit" disabled={!canSave || saving}>
          {saving ? "저장 중" : "저장"}
        </button>
      </div>
    </form>
  );
}
