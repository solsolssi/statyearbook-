import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { StatTable } from "../types";
import { buildTableUpdatePayload, TableEditView } from "./TableEditView";

afterEach(() => {
  cleanup();
});

function tableFixture(): StatTable {
  return {
    id: "db-10",
    code: "1-1-1",
    title: "인구",
    title_en: "Population",
    section_title: "인구 통계",
    section_title_en: "Population Statistics",
    domain: "행정",
    unit: "명",
    sheet_name: "",
    status: "normal",
    status_label: "정상",
    year_range: "2026",
    updated_at: "2026-01-01",
    theme: "blue",
    hierarchy: [],
    parts: [],
    columns: [
      { key: "c0", label: "구분", align: "left", source_col_index: 0 },
      { key: "c1", label: "2026", align: "right", source_col_index: 1 },
    ],
    rows: [{ _row_index: 1, _row_label: "합계", c0: "합계", c1: 10 }],
    summary: [],
    key_figures: [],
    checks: [],
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
      base_date: "2026 기준",
      base_date_display: "2026 기준",
      unit_display: "명",
      extracted_at: "",
      header_count: 1,
    },
  };
}

describe("buildTableUpdatePayload", () => {
  it("only emits coordinate patches for changed headers and cells", () => {
    const original = tableFixture();
    const unchanged = buildTableUpdatePayload(original, structuredClone(original));
    expect(unchanged.parts[0].columns).toEqual([]);
    expect(unchanged.parts[0].cells).toEqual([]);

    const draft = structuredClone(original);
    draft.columns[1].label = "2027";
    draft.rows[0].c1 = "25";
    draft.metadata.note = "수정됨";
    const payload = buildTableUpdatePayload(original, draft);

    expect(payload.parts[0].columns).toEqual([
      {
        source_col_indexes: [1],
        label: "2027",
        label_en: "",
        footnote_marker: "",
      },
    ]);
    expect(payload.parts[0].cells).toEqual([
      {
        row_index: 1,
        col_index: 1,
        value: "25",
        value_en: "",
        footnote_marker: "",
      },
    ]);
    expect(payload.parts[0].metadata.note).toBe("수정됨");
  });

  it("emits a shared hierarchy patch when a parent heading changes", () => {
    const original = tableFixture();
    original.code = "8-1-3-1";
    original.hierarchy = [
      { code: "8", title: "민방위" },
      { code: "8-1-3", title: "교육 훈련", title_en: "Education & Training" },
      { code: "8-1-3-1", title: "인구", title_en: "Population" },
    ];
    const draft = structuredClone(original);
    draft.code = "8-1-4-1";
    draft.section_title = "개정 교육 훈련";
    draft.section_title_en = "Revised Education";
    draft.hierarchy[1] = {
      code: "8-1-4",
      title: "개정 교육 훈련",
      title_en: "Revised Education",
    };

    const payload = buildTableUpdatePayload(original, draft);

    expect(payload.hierarchy_patches).toEqual([
      {
        kind: "section",
        original_code: "8-1-3",
        code: "8-1-4",
        title: "개정 교육 훈련",
        title_en: "Revised Education",
      },
    ]);
  });

  it("keeps the detail-style table until a title, header, or cell is selected", () => {
    render(createElement(TableEditView, {
      table: tableFixture(),
      reportId: 1,
      accessToken: "token",
      onCancel: vi.fn(),
      onSaved: vi.fn(),
    }));

    expect(screen.queryByDisplayValue("Population")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "영문 제목 수정" }));
    expect(screen.getByDisplayValue("Population")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "2026 헤더 수정" }));
    expect(screen.getByRole("button", { name: "헤더 수정 닫기" })).toBeTruthy();
    expect(screen.getByDisplayValue("2026")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "1행 2026 수정" }));
    expect(screen.getByRole("button", { name: "1행 · 2026 닫기" })).toBeTruthy();
    expect(screen.getByDisplayValue("10")).toBeTruthy();
  });

  it("applies edits only when Apply is selected", () => {
    render(createElement(TableEditView, {
      table: tableFixture(),
      reportId: 1,
      accessToken: "token",
      onCancel: vi.fn(),
      onSaved: vi.fn(),
    }));

    const targetCell = () => screen.getByRole("button", { name: "1행 2026 수정" });

    fireEvent.click(targetCell());
    fireEvent.change(screen.getByDisplayValue("10"), { target: { value: "99" } });
    fireEvent.click(screen.getByRole("button", { name: "1행 · 2026 닫기" }));
    expect(targetCell().textContent).toContain("10");

    fireEvent.click(targetCell());
    fireEvent.change(screen.getByDisplayValue("10"), { target: { value: "99" } });
    fireEvent.click(screen.getByRole("button", { name: "적용" }));
    expect(targetCell().textContent).toContain("99");
  });

  it("allows finishing edit mode without changes", () => {
    const onCancel = vi.fn();
    render(createElement(TableEditView, {
      table: tableFixture(),
      reportId: 1,
      accessToken: "token",
      onCancel,
      onSaved: vi.fn(),
    }));

    const doneButton = screen.getByRole("button", { name: "완료" });
    expect(doneButton).not.toHaveProperty("disabled", true);
    fireEvent.click(doneButton);
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
