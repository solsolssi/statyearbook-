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
});
