import type {
  ReportSummary,
  StatTable,
  StatTableSummary,
  StatTablePart,
  TableStatus,
  ValidationIssue,
} from "../types";

type ValidationTableLike = StatTable | StatTableSummary;
type GenerationReviewLike = Pick<
  ValidationTableLike,
  "generation_status" | "generation_status_label" | "incremental_reason_code"
>;

export const VALIDATION_CHECK_TYPES = [
  "합계 검수",
  "비율 검수",
  "오탈자 검수",
  "번역 검수",
  "메타정보 검수",
  "이상치 검수",
  "파란색 표기 확인",
  "재검수 필요",
] as const;

export const INCREMENTAL_REVIEW_TYPES = [
  "통계 번호 미연결",
  "증분 데이터 부족",
  "형식 불일치",
  "신규 통계",
] as const;

export const DEFAULT_HIDDEN_VALIDATION_TYPES = new Set<string>(["이상치 검수"]);
export const INTERNAL_VALIDATION_TYPES = new Set<string>(["검수 프로파일 확인"]);
export const REVALIDATION_REQUIRED_FILTER = "재검수 필요";
export const OPTIONAL_VALIDATION_TYPES = new Set<string>([
  "파란색 표기 확인",
  REVALIDATION_REQUIRED_FILTER,
  ...INCREMENTAL_REVIEW_TYPES,
]);

const INCREMENT_KEY_REVIEW_REASONS = new Set([
  "NO_INCREMENT_CANDIDATE",
  "NO_RELIABLE_CANDIDATE",
  "AMBIGUOUS_CANDIDATE",
  "REFERENCE_TABLE_AMBIGUOUS",
]);
const INCREMENT_DATA_REVIEW_REASONS = new Set([
  "MISSING_ITEM_METADATA",
  "UNDESCRIBED_VALUE_ITEMS",
  "NO_TARGET_VALUES",
  "TARGET_YEAR_MISSING",
]);
const INCREMENT_FORMAT_REVIEW_REASONS = new Set([
  "HEADER_STRUCTURE_MISMATCH",
  "ROW_STRUCTURE_MISMATCH",
  "ROW_LABEL_MISMATCH",
  "YEAR_COLUMN_ROW_MISMATCH",
  "YEAR_SEQUENCE_CONFLICT",
  "REFERENCE_STRUCTURE_MISMATCH",
  "REFERENCE_VALUE_MISMATCH",
]);

const GENERATION_REVIEW_STATUS_LABELS: Record<string, string> = {
  mapping_review: "증분 연결 확인",
  parse_review: "파싱 확인",
  new_table: "신규 통계 확인",
  source_missing: "증분 데이터 없음",
  unavailable: "생성 확인 필요",
  recipe_required: "생성 규칙 필요",
};

export function incrementalReviewType(
  table: Pick<ValidationTableLike, "generation_status" | "incremental_reason_code">,
): string | null {
  const generationStatus = table.generation_status ?? "";
  const reason = table.incremental_reason_code ?? "";
  if (generationStatus === "new_table" || reason === "UNMATCHED_NEW_INCREMENT") {
    return "신규 통계";
  }
  if (generationStatus === "source_missing" || INCREMENT_DATA_REVIEW_REASONS.has(reason)) {
    return "증분 데이터 부족";
  }
  if (
    INCREMENT_FORMAT_REVIEW_REASONS.has(reason)
    || generationStatus === "recipe_required"
    || reason === "MANUAL_EDIT_REQUIRES_REVIEW"
  ) {
    return "형식 불일치";
  }
  if (generationStatus === "mapping_review" || INCREMENT_KEY_REVIEW_REASONS.has(reason)) {
    return "통계 번호 미연결";
  }
  return null;
}

function tableChecks(table: ValidationTableLike): ValidationIssue[] {
  const partChecks =
    "parts" in table
      ? table.parts.flatMap((part) => part.checks)
      : [];
  return [...table.checks, ...partChecks];
}

function tableHasStaleValidation(table: ValidationTableLike) {
  return Boolean(
    table.validation_stale ||
      ("parts" in table && table.parts.some((part) => part.validation_stale)),
  );
}

export function validationTypesForTables(
  tables: ValidationTableLike[],
  preferredOrder: readonly string[] = VALIDATION_CHECK_TYPES,
  includeDiscoveredChecks: boolean = true,
) {
  const discovered = new Set<string>(
    preferredOrder.filter(
      (type) => !INTERNAL_VALIDATION_TYPES.has(type),
    ),
  );
  if (includeDiscoveredChecks) {
    for (const table of tables) {
      for (const check of tableChecks(table)) {
        if (INTERNAL_VALIDATION_TYPES.has(check.type)) {
          continue;
        }
        discovered.add(check.type);
      }
    }
  }
  return Array.from(discovered);
}

export function activeValidationTypesForTables(tables: ValidationTableLike[]) {
  const active = new Set<string>();
  for (const table of tables) {
    const incrementalType = incrementalReviewType(table);
    if (incrementalType) {
      active.add(incrementalType);
    }
    if (tableHasStaleValidation(table)) {
      active.add(REVALIDATION_REQUIRED_FILTER);
    }
    for (const check of tableChecks(table)) {
      if (INTERNAL_VALIDATION_TYPES.has(check.type)) {
        continue;
      }
      active.add(check.type);
      if (check.status === REVALIDATION_REQUIRED_FILTER) {
        active.add(REVALIDATION_REQUIRED_FILTER);
      }
    }
  }
  return active;
}

function visibleChecks(checks: ValidationIssue[], hiddenTypes: ReadonlySet<string>) {
  return checks.filter(
    (check) => {
      if (INTERNAL_VALIDATION_TYPES.has(check.type)) {
        return false;
      }
      if (check.status === REVALIDATION_REQUIRED_FILTER) {
        return !hiddenTypes.has(REVALIDATION_REQUIRED_FILTER);
      }
      return !hiddenTypes.has(check.type);
    },
  );
}

function statusFromChecks(
  checks: ValidationIssue[],
  normalLabel: string = "정상",
): { status: TableStatus; status_label: string } {
  const activeChecks = checks.filter((check) => check.status !== "정상");

  if (activeChecks.some((check) => check.status === "오류 의심" || check.severity === "critical")) {
    return { status: "suspected_error", status_label: "오류 의심" };
  }

  if (activeChecks.some((check) => check.status === "재검수 필요")) {
    return { status: "needs_review", status_label: "재검수 필요" };
  }

  if (activeChecks.length > 0) {
    return { status: "needs_review", status_label: "확인 필요" };
  }

  return { status: "normal", status_label: normalLabel };
}

function statusFromGenerationReview(
  table: GenerationReviewLike,
): { status: TableStatus; status_label: string } | null {
  const generationStatus = table.generation_status ?? "";
  const incrementalType = incrementalReviewType(table);
  const fallbackLabel = GENERATION_REVIEW_STATUS_LABELS[generationStatus];
  if (!fallbackLabel && !incrementalType) {
    return null;
  }
  return {
    status: "needs_review",
    status_label: incrementalType || table.generation_status_label || fallbackLabel,
  };
}

function partWithVisibleChecks(part: StatTablePart, hiddenTypes: ReadonlySet<string>): StatTablePart {
  const checks = visibleChecks(part.checks, hiddenTypes);
  if (part.is_test_table) {
    return { ...part, checks };
  }
  const generationType = incrementalReviewType(part);
  const generationStatus = statusFromGenerationReview(part);
  if (generationStatus && (!generationType || !hiddenTypes.has(generationType))) {
    return {
      ...part,
      checks,
      ...generationStatus,
    };
  }
  if (part.validation_stale && !hiddenTypes.has(REVALIDATION_REQUIRED_FILTER)) {
    return {
      ...part,
      checks,
      status: "needs_review",
      status_label: "재검수 필요",
    };
  }
  const status = statusFromChecks(
    checks,
    part.status === "normal" ? part.status_label : "정상",
  );

  return {
    ...part,
    checks,
    ...status,
  };
}

export function tablesWithValidationVisibility<T extends ValidationTableLike>(
  tables: T[],
  hiddenTypes: ReadonlySet<string>,
): T[] {
  return tables.map((table) => {
    const checks = visibleChecks(table.checks, hiddenTypes);
    if (table.is_test_table) {
      return {
        ...table,
        checks,
        ...("parts" in table
          ? { parts: table.parts.map((part) => partWithVisibleChecks(part, hiddenTypes)) }
          : {}),
      } as T;
    }
    const generationType = incrementalReviewType(table);
    const generationStatus = statusFromGenerationReview(table);
    if (generationStatus && (!generationType || !hiddenTypes.has(generationType))) {
      return {
        ...table,
        checks,
        ...("parts" in table
          ? { parts: table.parts.map((part) => partWithVisibleChecks(part, hiddenTypes)) }
          : {}),
        ...generationStatus,
      } as T;
    }
    // A manual change invalidates the prior validation result.  This must
    // take precedence over recalculating status from the now-stale checks;
    // otherwise fixing a previously failing cell would misleadingly show
    // the table as normal before validation runs again.
    if (table.validation_stale && !hiddenTypes.has(REVALIDATION_REQUIRED_FILTER)) {
      return {
        ...table,
        checks,
        ...("parts" in table
          ? { parts: table.parts.map((part) => partWithVisibleChecks(part, hiddenTypes)) }
          : {}),
        status: "needs_review",
        status_label: "재검수 필요",
      } as T;
    }
    const status = statusFromChecks(
      checks,
      table.status === "normal" ? table.status_label : "정상",
    );

    return {
      ...table,
      checks,
      ...("parts" in table
        ? { parts: table.parts.map((part) => partWithVisibleChecks(part, hiddenTypes)) }
        : {}),
      ...status,
    } as T;
  });
}

export function summaryWithValidationVisibility(
  summary: ReportSummary,
  tables: ValidationTableLike[],
): ReportSummary {
  const issueCounts: Record<string, number> = {};
  let normalCount = 0;
  let needsReviewCount = 0;
  let suspectedErrorCount = 0;

  for (const table of tables) {
    if (table.status === "normal") {
      normalCount += 1;
    } else if (table.status === "needs_review") {
      needsReviewCount += 1;
    } else if (table.status === "suspected_error") {
      suspectedErrorCount += 1;
    }

    for (const check of table.checks) {
      if (check.status === "정상") {
        continue;
      }
      issueCounts[check.type] = (issueCounts[check.type] ?? 0) + 1;
    }
  }

  return {
    ...summary,
    total_tables: tables.length,
    normal_count: normalCount,
    needs_review_count: needsReviewCount,
    suspected_error_count: suspectedErrorCount,
    issue_counts: issueCounts,
  };
}
