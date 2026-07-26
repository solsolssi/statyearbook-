import { describe, expect, it } from "vitest";

import type { ValidationIssue } from "../types";
import {
  VALIDATION_CHECK_TYPE_ORDER,
  groupedValidationIssueCount,
  relatedCellsForCheck,
  repeatedCalculationGroupKey,
  targetCellForCheck,
  validationDisplayGroupKey,
} from "./validationGrouping";

function check(overrides: Partial<ValidationIssue> = {}): ValidationIssue {
  return {
    id: "check-1",
    rule_id: "profile.sample.row_sum",
    type: "합계 검수",
    location: "합계 / 2025",
    row_index: 1,
    col_index: 2,
    current_value: "10",
    expected_value: "10",
    status: "정상",
    severity: "info",
    detail: "합계를 확인했습니다.",
    formula: "합계 = A + B",
    highlight_cells: [
      { row_index: 1, col_index: 2, role: "target" },
      { row_index: 2, col_index: 2, role: "related" },
    ],
    ...overrides,
  };
}

describe("validation grouping baseline", () => {
  it("keeps the reviewed validation type order", () => {
    expect(
      [...VALIDATION_CHECK_TYPE_ORDER.entries()]
        .sort((left, right) => left[1] - right[1])
        .map(([type]) => type),
    ).toEqual([
      "합계 검수",
      "비율 검수",
      "오탈자 검수",
      "번역 검수",
      "메타정보 검수",
      "이상치 검수",
      "파란색 표기 확인",
    ]);
  });

  it("groups repeated passing calculations but separates status", () => {
    const passing = check();
    const anotherPassing = check({ id: "check-2", row_index: 2 });
    const failed = check({ id: "check-3", status: "오류 의심" });

    expect(repeatedCalculationGroupKey(passing)).toBe(
      "합계 검수::합계 = A + B",
    );
    expect(validationDisplayGroupKey(passing)).toBe(
      validationDisplayGroupKey(anotherPassing),
    );
    expect(validationDisplayGroupKey(passing)).not.toBe(
      validationDisplayGroupKey(failed),
    );
    expect(groupedValidationIssueCount([passing, anotherPassing], "정상")).toBe(1);
  });

  it("uses the backend display group key when it is present", () => {
    const item = check({ display_group_key: "server::canonical-group" });

    expect(validationDisplayGroupKey(item)).toBe("server::canonical-group");
  });

  it("keeps target and operand highlights distinct", () => {
    const item = check();
    expect(targetCellForCheck(item)).toEqual({
      row_index: 1,
      col_index: 2,
      role: "target",
    });
    expect(relatedCellsForCheck(item)).toEqual([
      { row_index: 2, col_index: 2, role: "related" },
    ]);
  });
});
