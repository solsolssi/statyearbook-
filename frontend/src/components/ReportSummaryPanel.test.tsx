import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReportOption, ReportSummary } from "../types";
import { ReportSummaryPanel } from "./ReportSummaryPanel";

const availableReports: ReportOption[] = [
  {
    id: 61,
    year: 2026,
    title: "2026 hwpx",
    file_name: "2026.hwpx",
    imported_at: "2026-08-03 10:04:48",
    table_count: 366,
    kind: "published",
  },
  {
    id: 85,
    year: 2025,
    title: "2025 행정안전통계연보",
    file_name: "2025.hwpx",
    imported_at: "2026-08-09 23:19:14",
    table_count: 363,
    kind: "published",
  },
];

function ledgerGeneratedSummary(): ReportSummary {
  return {
    report_id: 88,
    file_name: "증분업로드",
    base_year: "2026",
    total_tables: 363,
    normal_count: 0,
    needs_review_count: 363,
    suspected_error_count: 0,
    issue_counts: {},
    origin_kind: "ledger_generated",
    base_report_id: 85,
    validation_scope: "none",
  };
}

describe("ReportSummaryPanel", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("places validation controls below the summary cards without the upload notice", () => {
    render(
      <ReportSummaryPanel
        summary={ledgerGeneratedSummary()}
        datasetLabel="통계 연보"
        availableReports={availableReports}
        selectedReportId="88"
        activeFilter="all"
        validationTypes={["합계 검수", "비율 검수"]}
        disabledValidationTypes={new Set()}
        validationCatalog={[]}
        hiddenValidationTypes={new Set()}
        validationRunState="idle"
        deleteState="idle"
        onReportChange={vi.fn()}
        onFilterChange={vi.fn()}
        onValidationTypeVisibilityChange={vi.fn()}
        onShowAllValidationTypes={vi.fn()}
        onHideAllValidationTypes={vi.fn()}
        onRunValidation={vi.fn().mockResolvedValue(true)}
        onDeleteReport={vi.fn().mockResolvedValue(true)}
      />,
    );

    expect(screen.queryByText("연보 업로드 완료")).toBeNull();
    expect(screen.queryByText("원장 기반 연보 생성")).toBeNull();
    expect(screen.getByText("검수 항목")).toBeTruthy();
    expect(screen.getByRole("button", { name: "검수 진행" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "검수 진행" }).closest(".summary-control-row"),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "연보 다운" }).closest(".dataset-selector"),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "연보 다운" }).closest(".summary-control-row"),
    ).toBeNull();
  });

  it.each([
    ["shared", "동일 표 검수 결과 공유"],
    ["selected", "선택 항목 검수 완료"],
    ["changed_tables", "변경 표 부분 검수"],
  ] as const)("does not show the validation scope notice for %s reports", (scope, notice) => {
    render(
      <ReportSummaryPanel
        summary={{ ...ledgerGeneratedSummary(), validation_scope: scope }}
        datasetLabel="통계 연보"
        availableReports={availableReports}
        selectedReportId="88"
        activeFilter="all"
        validationTypes={["합계 검수", "비율 검수"]}
        disabledValidationTypes={new Set()}
        validationCatalog={[]}
        hiddenValidationTypes={new Set()}
        validationRunState="idle"
        deleteState="idle"
        onReportChange={vi.fn()}
        onFilterChange={vi.fn()}
        onValidationTypeVisibilityChange={vi.fn()}
        onShowAllValidationTypes={vi.fn()}
        onHideAllValidationTypes={vi.fn()}
        onRunValidation={vi.fn().mockResolvedValue(true)}
        onDeleteReport={vi.fn().mockResolvedValue(true)}
      />,
    );

    expect(screen.queryByText(notice)).toBeNull();
  });

  it("allows deleting the currently opened ledger-generated report", async () => {
    const onDeleteReport = vi.fn().mockResolvedValue(true);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <ReportSummaryPanel
        summary={ledgerGeneratedSummary()}
        datasetLabel="통계 연보"
        availableReports={availableReports}
        selectedReportId="88"
        activeFilter="all"
        validationTypes={[]}
        disabledValidationTypes={new Set()}
        validationCatalog={[]}
        hiddenValidationTypes={new Set()}
        validationRunState="idle"
        deleteState="idle"
        onReportChange={vi.fn()}
        onFilterChange={vi.fn()}
        onValidationTypeVisibilityChange={vi.fn()}
        onShowAllValidationTypes={vi.fn()}
        onHideAllValidationTypes={vi.fn()}
        onRunValidation={vi.fn().mockResolvedValue(true)}
        onDeleteReport={onDeleteReport}
      />,
    );

    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("88");
    expect(screen.getByText("증분업로드 · 363개 표")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "연보 삭제" }));

    await waitFor(() => {
      expect(onDeleteReport).toHaveBeenCalledWith(
        expect.objectContaining({
          id: 88,
          title: "증분업로드",
        }),
      );
    });
  });
});
