import { useState } from "react";
import { Download, LoaderCircle, X } from "lucide-react";

import { downloadValidationReportArchive } from "../api/reportApi";

const reportStatuses = ["오류 의심", "확인 필요"] as const;
const reportContents = [
  { id: "validation_index", label: "검수 내역" },
  { id: "highlighted", label: "하이라이트 표" },
  { id: "metadata", label: "메타데이터" },
] as const;

export function ValidationReportDownloadDialog({
  reportId,
  reportTitle,
  onClose,
}: {
  reportId: number;
  reportTitle: string;
  onClose: () => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(reportStatuses),
  );
  const [selectedContents, setSelectedContents] = useState<Set<string>>(
    () => new Set(reportContents.map((content) => content.id)),
  );
  const [state, setState] = useState<"idle" | "downloading">("idle");

  function toggle(status: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(status)) next.delete(status);
      else next.add(status);
      return next;
    });
  }

  function toggleContent(content: string) {
    setSelectedContents((current) => {
      const next = new Set(current);
      if (next.has(content)) next.delete(content);
      else next.add(content);
      return next;
    });
  }

  async function download() {
    if (selected.size === 0 || selectedContents.size === 0 || state === "downloading") return;
    setState("downloading");
    try {
      await downloadValidationReportArchive(reportId, [...selected], [...selectedContents]);
      onClose();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "검수 리포트를 만들지 못했습니다.");
      setState("idle");
    }
  }

  return (
    <div className="upload-dialog-backdrop" role="presentation">
      <section
        className="upload-dialog validation-report-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="validation-report-title"
      >
        <div className="upload-dialog__header">
          <div>
            <h2 id="validation-report-title">검수 리포트</h2>
            <p>{reportTitle}</p>
          </div>
          <button className="icon-button" type="button" aria-label="닫기" onClick={onClose}>
            <X aria-hidden="true" size={20} />
          </button>
        </div>

        <div className="validation-report-filter">
          <strong>대상 상태</strong>
          <div className="validation-report-filter__options">
            {reportStatuses.map((status) => (
              <label key={status}>
                <input
                  type="checkbox"
                  checked={selected.has(status)}
                  onChange={() => toggle(status)}
                />
                <span>{status}</span>
              </label>
            ))}
          </div>
        </div>
        <div className="validation-report-filter">
          <strong>포함할 파일</strong>
          <div className="validation-report-filter__options">
            {reportContents.map((content) => (
              <label key={content.id}>
                <input
                  type="checkbox"
                  checked={selectedContents.has(content.id)}
                  onChange={() => toggleContent(content.id)}
                />
                <span>{content.label}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="upload-dialog__footer upload-dialog__footer--end">
          <button
            className="primary-button"
            type="button"
            disabled={selected.size === 0 || selectedContents.size === 0 || state === "downloading"}
            onClick={() => void download()}
          >
            {state === "downloading" ? (
              <LoaderCircle className="is-spinning" aria-hidden="true" size={17} />
            ) : (
              <Download aria-hidden="true" size={17} />
            )}
            {state === "downloading" ? "생성 중" : "리포트 다운로드"}
          </button>
        </div>
      </section>
    </div>
  );
}
