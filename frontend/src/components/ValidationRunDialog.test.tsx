import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ValidationCatalogItem } from "../types";
import { ValidationRunDialog } from "./ValidationRunDialog";

const catalog: ValidationCatalogItem[] = [
  {
    key: "sum",
    label: "합계 검수",
    order: 0,
    default_visible: true,
    default_status: "오류 의심",
    default_severity: "critical",
    description: "합계를 확인합니다.",
  },
  {
    key: "translation",
    label: "번역 검수",
    order: 1,
    default_visible: true,
    default_status: "확인 필요",
    default_severity: "warning",
    description: "번역을 확인합니다.",
  },
];

describe("ValidationRunDialog", () => {
  it("submits only the selected validation types", async () => {
    const onRun = vi.fn().mockResolvedValue(true);
    const onClose = vi.fn();
    render(
      <ValidationRunDialog
        reportId={100}
        reportTitle="2026 수정 연보"
        catalog={catalog}
        state="idle"
        onClose={onClose}
        onRun={onRun}
      />,
    );

    fireEvent.click(screen.getByLabelText(/번역 검수/));
    fireEvent.click(screen.getByRole("button", { name: "선택 항목 검수" }));

    await waitFor(() => {
      expect(onRun).toHaveBeenCalledWith({
        selectedRuleKeys: ["sum"],
        reuseExisting: true,
        includeProfileLlm: false,
        includeLanguageLlm: false,
        sourceValidationRunId: undefined,
      });
    });
    expect(onClose).toHaveBeenCalled();
  });

  it("allows LLM rule assistance even when language checks are not selected", async () => {
    const onRun = vi.fn().mockResolvedValue(true);
    const view = render(
      <ValidationRunDialog
        reportId={100}
        reportTitle="2027 신규 연보"
        catalog={catalog}
        state="idle"
        onClose={() => undefined}
        onRun={onRun}
      />,
    );
    const dialog = within(view.container);

    fireEvent.click(dialog.getByLabelText(/번역 검수/));
    fireEvent.click(dialog.getByLabelText(/합계·비율 프로파일 LLM 보조/));
    fireEvent.click(dialog.getByRole("button", { name: "선택 항목 검수" }));

    await waitFor(() => {
      expect(onRun).toHaveBeenCalledWith(expect.objectContaining({
        selectedRuleKeys: ["sum"],
        includeProfileLlm: true,
        includeLanguageLlm: false,
      }));
    });
  });

  it("disables profile LLM assistance when no calculation checks are selected", async () => {
    const onRun = vi.fn().mockResolvedValue(true);
    const view = render(
      <ValidationRunDialog
        reportId={100}
        reportTitle="2027 신규 연보"
        catalog={catalog}
        state="idle"
        onClose={() => undefined}
        onRun={onRun}
      />,
    );
    const dialog = within(view.container);

    fireEvent.click(dialog.getByLabelText(/합계 검수/));

    expect(
      (dialog.getByLabelText(/합계·비율 프로파일 LLM 보조/) as HTMLInputElement).disabled,
    ).toBe(true);

    fireEvent.click(dialog.getByRole("button", { name: "선택 항목 검수" }));

    await waitFor(() => {
      expect(onRun).toHaveBeenCalledWith(expect.objectContaining({
        selectedRuleKeys: ["translation"],
        includeProfileLlm: false,
      }));
    });
  });

  it("keeps language LLM separate from calculation profile assistance", async () => {
    const onRun = vi.fn().mockResolvedValue(true);
    const view = render(
      <ValidationRunDialog
        reportId={100}
        reportTitle="2027 신규 연보"
        catalog={catalog}
        state="idle"
        onClose={() => undefined}
        onRun={onRun}
      />,
    );
    const dialog = within(view.container);

    fireEvent.click(dialog.getByLabelText(/오탈자·번역 LLM 검수/));
    fireEvent.click(dialog.getByRole("button", { name: "선택 항목 검수" }));

    await waitFor(() => {
      expect(onRun).toHaveBeenCalledWith(expect.objectContaining({
        includeProfileLlm: false,
        includeLanguageLlm: true,
      }));
    });
  });
});
