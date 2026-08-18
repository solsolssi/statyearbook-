import { AlertTriangle, CheckCircle2, CircleHelp, GitBranch } from "lucide-react";

import type { TableStatus } from "../types";

const statusConfig = {
  normal: {
    label: "정상",
    icon: CheckCircle2,
  },
  needs_review: {
    label: "확인 필요",
    icon: CircleHelp,
  },
  suspected_error: {
    label: "오류 의심",
    icon: AlertTriangle,
  },
} satisfies Record<TableStatus, { label: string; icon: typeof CheckCircle2 }>;

const incrementalReviewLabels = new Set([
  "통계 번호 미연결",
  "증분 데이터 부족",
  "형식 불일치",
  "신규 통계",
]);

interface StatusBadgeProps {
  status: TableStatus;
  label?: string;
}

export function StatusBadge({ status, label }: StatusBadgeProps) {
  const config = statusConfig[status];
  const Icon = incrementalReviewLabels.has(label ?? "") ? GitBranch : config.icon;

  return (
    <span className={`status-badge status-badge--${status}`}>
      <Icon aria-hidden="true" size={14} />
      {label ?? config.label}
    </span>
  );
}
