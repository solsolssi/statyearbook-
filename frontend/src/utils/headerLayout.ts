import type { ColumnDefinition } from "../types";

export interface HeaderLayoutCell {
  key: string;
  columnIndexes: number[];
  label: string;
  labelEn: string;
  colSpan: number;
  rowSpan: number;
  isLeaf: boolean;
}

function path(value: string[] | undefined, fallback: string) {
  const fromValue = value?.map((item) => item.trim()).filter(Boolean) ?? [];
  return fromValue.length > 0
    ? fromValue
    : fallback.split("/").map((item) => item.trim()).filter(Boolean);
}

export function headerPathFor(column: ColumnDefinition) {
  return path(column.header_path, column.label);
}

export function headerPathEnFor(column: ColumnDefinition) {
  return path(column.header_path_en, column.label_en ?? "");
}

/** Turn per-column header paths into HTML table cells with rowspan/colspan. */
export function headerLayout(columns: ColumnDefinition[]): HeaderLayoutCell[][] {
  const paths = columns.map(headerPathFor);
  const englishPaths = columns.map(headerPathEnFor);
  const depth = Math.max(1, ...paths.map((item) => item.length));

  return Array.from({ length: depth }, (_, level) => {
    const cells: HeaderLayoutCell[] = [];
    let index = 0;
    while (index < columns.length) {
      const currentPath = paths[index];
      if (level >= currentPath.length) {
        index += 1;
        continue;
      }
      const isLeaf = level === currentPath.length - 1;
      if (isLeaf) {
        cells.push({
          key: `${level}-${index}`,
          columnIndexes: [index],
          label: currentPath[level],
          labelEn: englishPaths[index][level] ?? "",
          colSpan: 1,
          rowSpan: depth - level,
          isLeaf: true,
        });
        index += 1;
        continue;
      }

      const prefix = currentPath.slice(0, level + 1).join("\u0000");
      let end = index + 1;
      while (end < columns.length) {
        const candidate = paths[end];
        if (candidate.length <= level + 1 || candidate.slice(0, level + 1).join("\u0000") !== prefix) {
          break;
        }
        end += 1;
      }
      cells.push({
        key: `${level}-${index}-${end}`,
        columnIndexes: Array.from({ length: end - index }, (_, offset) => index + offset),
        label: currentPath[level],
        labelEn: englishPaths[index][level] ?? "",
        colSpan: end - index,
        rowSpan: 1,
        isLeaf: false,
      });
      index = end;
    }
    return cells;
  });
}
