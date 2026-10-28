import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { StatTable } from "../types";
import { buildTableUpdatePayload, TableEditView } from "./TableEditView";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
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

  it("sends the complete visible matrix when rows or columns change", () => {
    const original = tableFixture();
    const draft = structuredClone(original);
    draft.columns.push({
      key: "new_column",
      label: "새 열",
      align: "right",
      source_col_index: 2,
      source_col_indexes: [2],
    });
    draft.rows.push({
      _row_index: -1,
      _row_label: "추가 행",
      c0: "추가 행",
      c1: 2,
      new_column: 3,
    });

    const payload = buildTableUpdatePayload(original, draft);

    expect(payload.parts[0].replace_structure).toBe(true);
    expect(payload.parts[0].header_count).toBe(1);
    expect(payload.parts[0].columns).toHaveLength(3);
    expect(payload.parts[0].cells).toHaveLength(6);
    expect(payload.parts[0].cells.at(-1)).toEqual({
      row_index: 2,
      col_index: 2,
      value: "3",
      value_en: "",
      footnote_marker: "",
    });
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

  it("discards every pending change when the explicit cancel button is selected", () => {
    const onCancel = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(createElement(TableEditView, {
      table: tableFixture(),
      reportId: 1,
      accessToken: "token",
      onCancel,
      onSaved: vi.fn(),
    }));

    fireEvent.click(screen.getByRole("button", { name: "1행 2026 수정" }));
    fireEvent.change(screen.getByDisplayValue("10"), { target: { value: "99" } });
    fireEvent.click(screen.getByRole("button", { name: "적용" }));
    fireEvent.click(screen.getByRole("button", { name: "취소" }));

    expect(window.confirm).toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("removes a column by dragging it to the thin edge control", () => {
    render(createElement(TableEditView, {
      table: tableFixture(),
      reportId: 1,
      accessToken: "token",
      onCancel: vi.fn(),
      onSaved: vi.fn(),
    }));
    const dataTransfer = {
      effectAllowed: "move",
      dropEffect: "move",
      setData: vi.fn(),
    };

    const columnHeader = screen.getByRole("button", { name: "2026 헤더 수정" }).closest("th");
    if (!columnHeader) throw new Error("열 헤더를 찾지 못했습니다.");
    fireEvent.dragStart(columnHeader, { dataTransfer });
    const trash = screen.getByRole("button", { name: "열 삭제 영역" });
    fireEvent.dragOver(trash, { dataTransfer });
    fireEvent.drop(trash, { dataTransfer });

    expect(screen.queryByRole("button", { name: "2026 헤더 수정" })).toBeNull();
  });

  it("trims trailing columns by dragging the plus edge inward", () => {
    render(createElement(TableEditView, {
      table: tableFixture(),
      reportId: 1,
      accessToken: "token",
      onCancel: vi.fn(),
      onSaved: vi.fn(),
    }));
    const table = document.querySelector("table");
    const headers = Array.from(document.querySelectorAll("thead th"));
    if (!table || headers.length !== 2) throw new Error("표 헤더를 찾지 못했습니다.");
    vi.spyOn(table, "getBoundingClientRect").mockReturnValue({
      left: 0, top: 0, right: 200, bottom: 100, width: 200, height: 100,
      x: 0, y: 0, toJSON: () => ({}),
    });
    headers.forEach((header, index) => {
      vi.spyOn(header, "getBoundingClientRect").mockReturnValue({
        left: index * 100, top: 0, right: (index + 1) * 100, bottom: 40,
        width: 100, height: 40, x: index * 100, y: 0, toJSON: () => ({}),
      });
    });
    const columnEdge = screen.getByRole("button", { name: "열 추가" });
    fireEvent.pointerDown(columnEdge, { pointerId: 1, clientX: 200, clientY: 50 });
    fireEvent.pointerMove(columnEdge, { pointerId: 1, clientX: 140, clientY: 50 });
    fireEvent.pointerUp(columnEdge, { pointerId: 1, clientX: 140, clientY: 50 });

    expect(screen.queryByRole("button", { name: "2026 헤더 수정" })).toBeNull();
    expect(screen.getByRole("button", { name: "구분 헤더 수정" })).toBeTruthy();
  });

  it("deletes a duplicated row with its delete button after confirmation", () => {
    const source = tableFixture();
    source.rows.push({ _row_index: 2, _row_label: "중복", c0: "중복", c1: 10 });
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(createElement(TableEditView, {
      table: source,
      reportId: 1,
      accessToken: "token",
      onCancel: vi.fn(),
      onSaved: vi.fn(),
    }));

    fireEvent.click(screen.getByRole("button", { name: "2행 삭제" }));
    expect(confirm).toHaveBeenLastCalledWith("2행 ‘중복’을 삭제할까요?");
    expect(screen.getByRole("button", { name: "2행 구분 수정" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "2행 삭제" }));
    expect(screen.queryByRole("button", { name: "2행 구분 수정" })).toBeNull();
    expect(screen.getByRole("button", { name: "1행 구분 수정" }).textContent).toContain("합계");
  });

  it("keeps at least one row when deleting", () => {
    const alert = vi.spyOn(window, "alert").mockImplementation(() => undefined);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(createElement(TableEditView, {
      table: tableFixture(),
      reportId: 1,
      accessToken: "token",
      onCancel: vi.fn(),
      onSaved: vi.fn(),
    }));

    fireEvent.click(screen.getByRole("button", { name: "1행 삭제" }));

    expect(alert).toHaveBeenCalledWith("표에는 행이 한 개 이상 있어야 합니다.");
    expect(screen.getByRole("button", { name: "1행 구분 수정" })).toBeTruthy();
  });

  it("sends renumbered rows after a row is deleted", () => {
    const original = tableFixture();
    original.rows.push(
      { _row_index: 2, _row_label: "중복", c0: "중복", c1: 10 },
      { _row_index: 3, _row_label: "다음", c0: "다음", c1: 5 },
    );
    const draft = structuredClone(original);
    draft.rows.splice(1, 1);

    const payload = buildTableUpdatePayload(original, draft);

    expect(payload.parts[0].replace_rows).toBe(true);
    expect(payload.parts[0].cells.map((cell) => [cell.row_index, cell.value])).toEqual([
      [1, "합계"], [1, "10"], [2, "다음"], [2, "5"],
    ]);
  });

  it("keeps the printed thousands separators when rows are rewritten", () => {
    const original = tableFixture();
    original.rows = [
      { _row_index: 1, _row_label: "합계", c0: "합계", c1: 8370, c1_text: "8,370" },
      { _row_index: 2, _row_label: "중복", c0: "중복", c1: 53 },
      { _row_index: 3, _row_label: "연도", c0: "연도", c1: 2026 },
    ];
    const draft = structuredClone(original);
    draft.rows.splice(1, 1);

    const payload = buildTableUpdatePayload(original, draft);

    expect(payload.parts[0].cells.map((cell) => cell.value)).toEqual(["합계", "8,370", "연도", "2026"]);
  });

  it("saves the edited value instead of the printed notation", () => {
    const original = tableFixture();
    original.rows = [{ _row_index: 1, _row_label: "합계", c0: "합계", c1: 8370, c1_text: "8,370" }];
    const draft = structuredClone(original);
    draft.rows[0].c1 = "9,000";

    const payload = buildTableUpdatePayload(original, draft);

    expect(payload.parts[0].cells).toEqual([
      { row_index: 1, col_index: 1, value: "9,000", value_en: "", footnote_marker: "" },
    ]);
  });

  it("reorders rows by dragging one row handle onto another row", () => {
    const source = tableFixture();
    source.rows.push({ _row_index: 2, _row_label: "둘째", c0: "둘째", c1: 20 });
    render(createElement(TableEditView, {
      table: source,
      reportId: 1,
      accessToken: "token",
      onCancel: vi.fn(),
      onSaved: vi.fn(),
    }));
    const dataTransfer = {
      effectAllowed: "move",
      dropEffect: "move",
      setData: vi.fn(),
    };

    const secondRow = screen.getByRole("button", { name: "2행 구분 수정" }).closest("tr");
    if (!secondRow) throw new Error("두 번째 행을 찾지 못했습니다.");
    fireEvent.dragStart(secondRow, { dataTransfer });
    const firstRowCell = screen.getByRole("button", { name: "1행 구분 수정" }).closest("tr");
    if (!firstRowCell) throw new Error("첫 번째 행을 찾지 못했습니다.");
    fireEvent.dragOver(firstRowCell, { dataTransfer });
    fireEvent.drop(firstRowCell, { dataTransfer });

    expect(screen.getByRole("button", { name: "1행 구분 수정" }).textContent).toContain("둘째");
  });
});
