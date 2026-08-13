import { describe, expect, it } from "vitest";

import type { StatTable, ValidationIssue } from "../types";
import {
  DEFAULT_HIDDEN_VALIDATION_TYPES,
  tablesWithValidationVisibility,
  validationTypesForTables,
} from "./validationVisibility";

function issue(type: string, status: string, severity: ValidationIssue["severity"]): ValidationIssue {
  return {
    id: `${type}-${status}`,
    type,
    location: "테스트",
    current_value: "",
    status,
    severity,
    detail: "",
  };
}

function table(checks: ValidationIssue[]): StatTable {
  return {
    id: "group-sample",
    code: "1-1-1",
    title: "테스트",
    title_en: "Test",
    section_title: "테스트",
    section_title_en: "Test",
    domain: "통계",
    unit: "개",
    sheet_name: "",
    status: "needs_review",
    status_label: "확인 필요",
    year_range: "2025",
    updated_at: "",
    theme: "blue",
    hierarchy: [],
    parts: [],
    columns: [],
    rows: [],
    summary: [],
    key_figures: [],
    checks,
    changes: [],
    visualizations: [],
    metadata: {
      original_file: "",
      sheet_name: "",
      note: "",
      source: "",
      source_department: "",
      source_officer: "",
      source_extension: "",
      source_reference: "",
      base_date: "",
      base_date_display: "",
      unit_display: "",
      extracted_at: "",
    },
  };
}

describe("validation visibility baseline", () => {
  it("hides only outlier checks by default and recalculates status", () => {
    const source = table([
      issue("합계 검수", "정상", "info"),
      issue("이상치 검수", "확인 필요", "warning"),
    ]);
    const [visible] = tablesWithValidationVisibility(
      [source],
      DEFAULT_HIDDEN_VALIDATION_TYPES,
    );

    expect(visible.checks.map((check) => check.type)).toEqual(["합계 검수"]);
    expect(visible.status).toBe("normal");
    expect(visible.status_label).toBe("정상");
  });

  it("keeps the catalog order before discovered custom types", () => {
    const types = validationTypesForTables([
      table([issue("사용자 정의 검수", "정상", "info")]),
    ]);
    expect(types.slice(0, 7)).toEqual([
      "합계 검수",
      "비율 검수",
      "오탈자 검수",
      "번역 검수",
      "메타정보 검수",
      "이상치 검수",
      "파란색 표기 확인",
    ]);
    expect(types.at(-1)).toBe("사용자 정의 검수");
  });

  it("excludes internal profile checks from filters and visible status", () => {
    const source = table([
      issue("검수 프로파일 확인", "확인 필요", "warning"),
      issue("합계 검수", "정상", "info"),
    ]);
    const types = validationTypesForTables([source]);
    const [visible] = tablesWithValidationVisibility([source], new Set());

    expect(types).not.toContain("검수 프로파일 확인");
    expect(visible.checks.map((check) => check.type)).toEqual(["합계 검수"]);
    expect(visible.status).toBe("normal");
  });

  it("keeps manually edited tables in the review queue until validation runs again", () => {
    const source = {
      ...table([issue("합계 검수", "오류 의심", "critical")]),
      validation_stale: true,
    };
    const [visible] = tablesWithValidationVisibility(
      [source],
      DEFAULT_HIDDEN_VALIDATION_TYPES,
    );

    expect(visible.status).toBe("needs_review");
    expect(visible.status_label).toBe("재검수 필요");
    expect(visible.checks.map((check) => check.type)).toEqual(["합계 검수"]);
  });

  it("labels pending language checks as revalidation work", () => {
    const source = table([
      issue("번역 검수", "재검수 필요", "warning"),
    ]);
    const [visible] = tablesWithValidationVisibility([source], new Set());

    expect(visible.status).toBe("needs_review");
    expect(visible.status_label).toBe("재검수 필요");
  });
});
