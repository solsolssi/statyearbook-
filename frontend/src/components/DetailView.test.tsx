import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { StatTable, ValidationIssue } from "../types";
import { DetailView } from "./DetailView";

Element.prototype.scrollIntoView = vi.fn();

function validationIssue(): ValidationIssue {
  return {
    id: "check-pass",
    rule_id: "fixture.sum",
    type: "합계 검수",
    location: "합계 / 2025",
    row_index: 1,
    col_index: 1,
    current_value: "10",
    expected_value: "10",
    difference: "0",
    status: "정상",
    severity: "info",
    detail: "합계 검수 통과",
    formula: "합계 = 항목",
    highlight_scope: "cell",
    highlight_cells: [
      { row_index: 1, col_index: 1, role: "target" },
      { row_index: 2, col_index: 1, role: "related" },
    ],
    highlight_rows: [],
  };
}

function representativeTable(): StatTable {
  return {
    id: "group-fixture",
    code: "3-2-1-2",
    title: "대표 통계",
    title_en: "Representative Statistics",
    section_title: "대표 통계",
    section_title_en: "Representative Statistics",
    domain: "행정",
    unit: "건",
    sheet_name: "",
    status: "normal",
    status_label: "정상",
    year_range: "2025",
    updated_at: "2026-07-26",
    theme: "blue",
    hierarchy: [],
    parts: [],
    columns: [
      { key: "label", label: "구분", align: "left", source_col_index: 0 },
      { key: "value", label: "2025", align: "right", source_col_index: 1 },
    ],
    rows: [
      { _row_index: 1, _row_label: "합계", label: "합계", value: "10" },
      { _row_index: 2, _row_label: "항목", label: "항목", value: "10" },
    ],
    summary: [],
    key_figures: [],
    checks: [validationIssue()],
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
      base_date: "2025. 12. 31.",
      base_date_display: "2025. 12. 31.",
      unit_display: "건",
      extracted_at: "",
      header_count: 1,
    },
  };
}

describe("DetailView validation baseline", () => {
  it("keeps an empty status filter empty instead of showing another result", () => {
    render(
      <DetailView
        table={representativeTable()}
        validationTypes={["합계 검수"]}
        hiddenValidationTypes={new Set()}
        onValidationTypeVisibilityChange={vi.fn()}
        onShowAllValidationTypes={vi.fn()}
        onHideAllValidationTypes={vi.fn()}
        onBack={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /확인 필요/ }));
    expect(screen.getByText("해당 내용이 없습니다.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /통과/ }));
    expect(screen.getAllByText("합계 = 항목").length).toBeGreaterThan(0);
  });
});
