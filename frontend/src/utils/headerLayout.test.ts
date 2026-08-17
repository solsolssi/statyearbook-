import { describe, expect, it } from "vitest";

import type { ColumnDefinition } from "../types";
import { headerLayout } from "./headerLayout";

const columns: ColumnDefinition[] = [
  { key: "c0", label: "구분", align: "left", header_path: ["구분"] },
  { key: "c1", label: "발급 / 대면", align: "right", header_path: ["발급", "대면"] },
  { key: "c2", label: "발급 / 온라인", align: "right", header_path: ["발급", "온라인"] },
];

describe("headerLayout", () => {
  it("groups common parents and preserves a single-level header as a rowspan", () => {
    const rows = headerLayout(columns);

    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject([
      { label: "구분", colSpan: 1, rowSpan: 2, isLeaf: true },
      { label: "발급", colSpan: 2, rowSpan: 1, isLeaf: false },
    ]);
    expect(rows[1]).toMatchObject([
      { label: "대면", colSpan: 1, rowSpan: 1, isLeaf: true },
      { label: "온라인", colSpan: 1, rowSpan: 1, isLeaf: true },
    ]);
  });
});
