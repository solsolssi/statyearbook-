import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReportSummary, StatTableSummary, TableStatus, ValidationIssue } from "../types";
import { matchesWorkspaceFilter, ReportWorkspace } from "./ReportWorkspace";

function check(
  type: string,
  status: string = "정상",
  severity: ValidationIssue["severity"] = "info",
): ValidationIssue {
  return {
    id: type,
    rule_id: type,
    type,
    location: "전체 표",
    current_value: "",
    expected_value: "",
    difference: "",
    status,
    severity,
    detail: "",
  };
}

function table(
  checks: ValidationIssue[],
  validatedTypes: string[] = [],
  status: TableStatus = "normal",
): StatTableSummary {
  return {
    id: `db-${status}`,
    code: "2-1-5-2",
    title: "인감증명 발급",
    title_en: "",
    section_title: "",
    domain: "",
    status,
    status_label:
      status === "normal" ? "정상" : status === "needs_review" ? "확인 필요" : "오류 의심",
    theme: "blue",
    part_count: 1,
    summary: [],
    key_figures: [],
    checks,
    validated_types: validatedTypes,
  };
}

describe("matchesWorkspaceFilter", () => {
  afterEach(cleanup);

  it("keeps a normally-passed table when its selected check type was run", () => {
    expect(matchesWorkspaceFilter(table([check("비율 검수")]), "", "normal", new Set())).toBe(true);
  });

  it("keeps a normally-passed summary row using compact validation coverage", () => {
    expect(
      matchesWorkspaceFilter(table([], ["비율 검수"]), "", "normal", new Set()),
    ).toBe(true);
  });

  it("excludes a table with no check from the selected validation-type list", () => {
    expect(matchesWorkspaceFilter(table([]), "", "all", new Set())).toBe(false);
  });

  it("keeps tables without checks before validation starts", () => {
    expect(matchesWorkspaceFilter(table([]), "", "all", new Set(), "draft")).toBe(true);
    expect(matchesWorkspaceFilter(table([]), "", "all", new Set(), "unvalidated")).toBe(true);
  });

  it("keeps clean draft tables but excludes hidden draft diagnostic types", () => {
    const clean = table([]);
    const formatReview = {
      ...table([]),
      generation_status: "recipe_required",
      incremental_reason_code: "HEADER_STRUCTURE_MISMATCH",
    };

    expect(matchesWorkspaceFilter(clean, "", "all", new Set(["형식 불일치"]), "draft")).toBe(true);
    expect(
      matchesWorkspaceFilter(
        formatReview,
        "",
        "all",
        new Set(["형식 불일치"]),
        "draft",
      ),
    ).toBe(false);
  });

  it("keeps all status counts for the validation scope while a status list is selected", () => {
    const tables = [
      table([], ["합계 검수"], "normal"),
      table([check("합계 검수", "확인 필요", "warning")], ["합계 검수"], "needs_review"),
      table([check("합계 검수", "오류 의심", "critical")], ["합계 검수"], "suspected_error"),
    ];
    const summary: ReportSummary = {
      report_id: 1,
      file_name: "demo.md",
      base_year: "2026",
      total_tables: 3,
      normal_count: 1,
      needs_review_count: 1,
      suspected_error_count: 1,
      issue_counts: {},
      validation_scope: "full",
    };

    render(
      <ReportWorkspace
        datasetLabel="통계 연보"
        summary={summary}
        reviewStage="validated"
        availableReports={[]}
        tables={tables}
        selectedTableId="db-normal"
        selectedReportId="1"
        selectedTableDetail={null}
        query=""
        filter="normal"
        validationTypes={["합계 검수"]}
        disabledValidationTypes={new Set()}
        validationCatalog={[]}
        hiddenValidationTypes={new Set()}
        validationRunState="idle"
        deleteState="idle"
        tableListScrollTop={0}
        onReportChange={vi.fn()}
        onQueryChange={vi.fn()}
        onFilterChange={vi.fn()}
        onValidationTypeVisibilityChange={vi.fn()}
        onShowAllValidationTypes={vi.fn()}
        onHideAllValidationTypes={vi.fn()}
        onRunValidation={vi.fn().mockResolvedValue(true)}
        onDeleteReport={vi.fn().mockResolvedValue(true)}
        onSelect={vi.fn()}
        onOpen={vi.fn()}
        onTableListScrollTopChange={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "전체 표3" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "정상1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "확인 필요1" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "오류 의심1" })).toBeTruthy();
  });
});
