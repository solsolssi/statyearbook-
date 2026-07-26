import type { StatTablePart } from "../../types";

interface MetadataGridProps {
  part: StatTablePart;
  difference?: string;
}

export function MetadataGrid({ part, difference }: MetadataGridProps) {
  const hasProblem = (label: string) => difference?.includes(label) ?? false;

  return (
    <dl className="metadata-grid">
      <div className={hasProblem("기준일") ? "is-problem" : ""}>
        <dt>기준일</dt>
        <dd>{part.metadata.base_date_display || "-"}</dd>
      </div>
      <div className={hasProblem("단위") ? "is-problem" : ""}>
        <dt>단위</dt>
        <dd>{part.metadata.unit_display || "-"}</dd>
      </div>
      <div>
        <dt>최종 수정 일자</dt>
        <dd>{part.updated_at}</dd>
      </div>
      <div className={hasProblem("출처") ? "is-problem" : ""}>
        <dt>소속</dt>
        <dd>{part.metadata.source_department || "-"}</dd>
      </div>
      <div className={hasProblem("출처") ? "is-problem" : ""}>
        <dt>이름</dt>
        <dd>{part.metadata.source_officer || "-"}</dd>
      </div>
      <div className={hasProblem("출처") ? "is-problem" : ""}>
        <dt>내선번호</dt>
        <dd>{part.metadata.source_extension || "-"}</dd>
      </div>
      <div className={`metadata-grid__wide ${hasProblem("출처") ? "is-problem" : ""}`}>
        <dt>출처</dt>
        <dd>{part.metadata.source_reference || part.metadata.source || "-"}</dd>
      </div>
      <div className="metadata-grid__wide">
        <dt>주석</dt>
        <dd>{part.metadata.note || "-"}</dd>
      </div>
    </dl>
  );
}

