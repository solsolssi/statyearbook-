import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ValidationTypeFilter } from "./ValidationTypeFilter";

describe("ValidationTypeFilter", () => {
  it("shows visibility count and reports checkbox changes", () => {
    const onVisibilityChange = vi.fn();
    render(
      <ValidationTypeFilter
        types={["합계 검수", "비율 검수", "이상치 검수"]}
        hiddenTypes={new Set(["이상치 검수"])}
        onVisibilityChange={onVisibilityChange}
        onShowAll={vi.fn()}
        onHideAll={vi.fn()}
      />,
    );

    expect(screen.getByText("2/3")).toBeTruthy();
    const outlier = screen.getByLabelText("이상치 검수");
    expect((outlier as HTMLInputElement).checked).toBe(false);
    fireEvent.click(outlier);
    expect(onVisibilityChange).toHaveBeenCalledWith("이상치 검수", true);
  });

  it("keeps optional missing filters visible but disabled", () => {
    const onVisibilityChange = vi.fn();
    render(
      <ValidationTypeFilter
        types={["합계 검수", "파란색 표기 확인", "재검수 필요"]}
        hiddenTypes={new Set()}
        disabledTypes={new Set(["파란색 표기 확인", "재검수 필요"])}
        onVisibilityChange={onVisibilityChange}
        onShowAll={vi.fn()}
        onHideAll={vi.fn()}
      />,
    );

    expect(screen.getByText("1/1")).toBeTruthy();
    expect((screen.getByLabelText("파란색 표기 확인") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText("재검수 필요") as HTMLInputElement).disabled).toBe(true);

    fireEvent.click(screen.getByText("모두 숨기기"));
    expect(onVisibilityChange).toHaveBeenCalledWith("합계 검수", false);
    expect(onVisibilityChange).not.toHaveBeenCalledWith("파란색 표기 확인", false);
  });
});
