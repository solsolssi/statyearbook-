import type { ReportOption, StatTable, StatTablePart } from "../types";

export interface ReportWorkbookSelection {
  report: Pick<ReportOption, "id" | "year" | "title" | "file_name" | "table_count">;
  tables: StatTable[];
}

export function downloadTableCsv(table: StatTable) {
  const rows = downloadRows(table);
  const csv = rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
  downloadBlob(blob, `${baseFilename(table)}.csv`);
}

export function downloadTableXlsx(table: StatTable) {
  const workbook = createXlsxWorkbook(downloadSheets(table));
  const blob = new Blob([workbook], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  downloadBlob(blob, `${baseFilename(table)}.xlsx`);
}

export function downloadReportsXlsx(selections: ReportWorkbookSelection[]) {
  const workbook = createXlsxWorkbook(reportWorkbookSheets(selections));
  const blob = new Blob([workbook], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  downloadBlob(blob, reportWorkbookFilename(selections));
}

function downloadRows(table: StatTable) {
  return downloadParts(table).flatMap((part, index) => [
    ...(index === 0 ? [] : [[], []]),
    [`표 ${index + 1}`, part.part_label || part.code || part.title],
    ["메타데이터"],
    ...metadataRows(table, part),
    [],
    ["표"],
    ...tableRows(part),
  ]);
}

function downloadSheets(table: StatTable) {
  return downloadParts(table).map((part, index) => ({
    title: sheetTitle(table, part, index),
    rows: [
      ["메타데이터"],
      ...metadataRows(table, part),
      [],
      ["표"],
      ...tableRows(part),
    ],
  }));
}

function reportWorkbookSheets(selections: ReportWorkbookSelection[]) {
  const tablePartRows = selections.flatMap((selection) =>
    selection.tables.flatMap((table) =>
      downloadParts(table).map((part, partIndex) => ({
        report: selection.report,
        table,
        part,
        partIndex,
      })),
    ),
  );

  return [
    {
      title: "목차",
      rows: [
        ["선택 연보 수", String(selections.length)],
        [
          "전체 표 수",
          String(selections.reduce((sum, selection) => sum + selection.tables.length, 0)),
        ],
        ["전체 시트 수", String(tablePartRows.length)],
        [],
        ["연보", "연보 ID", "표 번호", "표 제목", "하위 표", "행 수", "열 수"],
        ...tablePartRows.map(({ report, table, part }) => [
          report.title || report.file_name || String(report.year),
          String(report.id),
          part.code || table.code,
          part.title || table.title,
          part.part_label,
          String(part.rows.length),
          String(part.columns.length),
        ]),
      ],
    },
    ...tablePartRows.map(({ report, table, part, partIndex }) => ({
      title: `${report.year}_${part.code || table.code}_${part.part_label || partIndex + 1}`,
      rows: [
        ["연보"],
        ["연보 ID", String(report.id)],
        ["연보 연도", String(report.year)],
        ["연보 제목", report.title],
        ["원본 파일", report.file_name],
        [],
        ["메타데이터"],
        ...metadataRows(table, part),
        [],
        ["표"],
        ...tableRows(part),
      ],
    })),
  ];
}

function downloadParts(table: StatTable): StatTablePart[] {
  if (table.parts.length > 0) {
    return table.parts;
  }
  return [
    {
      id: table.id,
      code: table.code,
      title: table.title,
      title_en: table.title_en,
      part_label: table.part_label ?? "원본 표",
      unit: table.unit,
      status: table.status,
      status_label: table.status_label,
      updated_at: table.updated_at,
      columns: table.columns,
      rows: table.rows,
      checks: table.checks,
      changes: table.changes,
      visualizations: table.visualizations,
      metadata: table.metadata,
      is_test_table: table.is_test_table,
      generation_status: table.generation_status,
      generation_status_label: table.generation_status_label,
      generation_message: table.generation_message,
      update_mode: table.update_mode,
      source_dataset_title: table.source_dataset_title,
      validation_stale: table.validation_stale,
    },
  ];
}

function metadataRows(table: StatTable, part: StatTablePart) {
  const metadata = part.metadata;
  return compactRows([
    ["표 번호", part.code || table.code],
    ["하위 표", part.part_label],
    ["표 제목", part.title || table.title],
    ["표 영문 제목", part.title_en || table.title_en],
    ["상태", part.status_label || table.status_label],
    ["분야", table.domain],
    ["장·절 제목", table.section_title],
    ["장·절 영문 제목", table.section_title_en],
    ["기준일", metadata.base_date],
    ["단위", part.unit || metadata.unit_display],
    ["최종 수정일", part.updated_at],
    ["소속", metadata.source_department],
    ["이름", metadata.source_officer],
    ["내선번호", metadata.source_extension],
    ["출처", metadata.source_reference],
    ["주석", metadata.note],
    ["원본 파일", metadata.original_file],
    ["시트", metadata.sheet_name],
    ["추출일", metadata.extracted_at],
  ]);
}

function tableRows(part: StatTablePart) {
  const labelRow = part.columns.map((column) => withFootnote(column.label, column.footnote_marker));
  const hasEnglishHeader = part.columns.some((column) => column.label_en?.trim());
  const headerRows = hasEnglishHeader ? [labelRow, part.columns.map((column) => column.label_en ?? "")] : [labelRow];
  return [
    ...headerRows,
    ...part.rows.map((row) =>
      part.columns.map((column) =>
        withEnglish(
          visibleCellValue(row[column.key]),
          visibleCellValue(row[`${column.key}_en`]),
          visibleCellValue(row[`${column.key}_footnote`]),
        ),
      ),
    ),
  ];
}

function compactRows(rows: string[][]) {
  return rows.filter(([, value]) => value?.trim());
}

function visibleCellValue(value: string | number | undefined) {
  return value === undefined || value === null ? "" : String(value);
}

function withEnglish(value: string, english: string, footnote: string) {
  const display = withFootnote(value, footnote);
  return english.trim() ? `${display}\n${english}` : display;
}

function withFootnote(value: string, footnote?: string) {
  return footnote?.trim() ? `${value}${footnote}` : value;
}

function csvCell(value: string) {
  return `"${value.replace(/"/g, '""')}"`;
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function baseFilename(table: StatTable) {
  return `${filenamePart(table.code)}_${filenamePart(table.title)}`;
}

function reportWorkbookFilename(selections: ReportWorkbookSelection[]) {
  if (selections.length === 1) {
    const [selection] = selections;
    return `${filenamePart(String(selection.report.year))}_${filenamePart(selection.report.title)}_전체통계.xlsx`;
  }
  return `전체통계_${selections.length}개_연보.xlsx`;
}

function filenamePart(value: string) {
  return (
    value
      .trim()
      .replace(/[\\/:*?"<>|]+/g, "_")
      .replace(/\s+/g, "_")
      .slice(0, 80) || "table"
  );
}

function createXlsxWorkbook(sheets: Array<{ title: string; rows: string[][] }>) {
  const sheetNames = uniqueSheetNames(sheets.map((sheet) => sheet.title));
  return zipFiles([
    {
      path: "[Content_Types].xml",
      content: xml(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  ${sheets
    .map(
      (_sheet, index) =>
        `<Override PartName="/xl/worksheets/sheet${index + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`,
    )
    .join("\n  ")}
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>`),
    },
    {
      path: "_rels/.rels",
      content: xml(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`),
    },
    {
      path: "xl/workbook.xml",
      content: xml(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    ${sheetNames
      .map(
        (sheetName, index) =>
          `<sheet name="${escapeXml(sheetName)}" sheetId="${index + 1}" r:id="rId${index + 1}"/>`,
      )
      .join("\n    ")}
  </sheets>
</workbook>`),
    },
    {
      path: "xl/_rels/workbook.xml.rels",
      content: xml(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  ${sheets
    .map(
      (_sheet, index) =>
        `<Relationship Id="rId${index + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${index + 1}.xml"/>`,
    )
    .join("\n  ")}
  <Relationship Id="rId${sheets.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`),
    },
    {
      path: "xl/styles.xml",
      content: xml(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
</styleSheet>`),
    },
    ...sheets.map((sheet, index) => ({
      path: `xl/worksheets/sheet${index + 1}.xml`,
      content: xml(sheetXml(sheet.rows)),
    })),
  ]);
}

function sheetXml(rows: string[][]) {
  const rowXml = rows
    .map((row, rowIndex) => {
      const cells = row
        .map((value, columnIndex) => {
          const reference = `${columnName(columnIndex + 1)}${rowIndex + 1}`;
          return `<c r="${reference}" t="inlineStr"><is><t xml:space="preserve">${escapeXml(value)}</t></is></c>`;
        })
        .join("");
      return `<row r="${rowIndex + 1}">${cells}</row>`;
    })
    .join("");
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetViews><sheetView workbookViewId="0"/></sheetViews>
  <sheetData>${rowXml}</sheetData>
</worksheet>`;
}

function safeSheetName(value: string) {
  const normalized = value.trim().replace(/[\[\]:*?/\\]/g, " ").replace(/\s+/g, " ");
  return (normalized || "통계표").slice(0, 31);
}

function sheetTitle(table: StatTable, part: StatTablePart, index: number) {
  return part.part_label || part.code || part.title || `${table.title} ${index + 1}`;
}

function uniqueSheetNames(values: string[]) {
  const used = new Set<string>();
  return values.map((value, index) => {
    const base = safeSheetName(value);
    if (!used.has(base)) {
      used.add(base);
      return base;
    }
    for (let suffixIndex = index + 1; suffixIndex < index + 1000; suffixIndex += 1) {
      const suffix = `_${suffixIndex}`;
      const candidate = `${base.slice(0, 31 - suffix.length)}${suffix}`;
      if (!used.has(candidate)) {
        used.add(candidate);
        return candidate;
      }
    }
    const fallback = base.slice(0, 31);
    used.add(fallback);
    return fallback;
  });
}

function columnName(index: number) {
  let value = "";
  let current = index;
  while (current > 0) {
    const remainder = (current - 1) % 26;
    value = String.fromCharCode(65 + remainder) + value;
    current = Math.floor((current - 1) / 26);
  }
  return value;
}

function escapeXml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function xml(value: string) {
  return new TextEncoder().encode(value.trim());
}

function zipFiles(files: Array<{ path: string; content: Uint8Array }>) {
  const encoder = new TextEncoder();
  const localParts: Uint8Array[] = [];
  const centralParts: Uint8Array[] = [];
  let offset = 0;
  const { dosTime, dosDate } = zipDate(new Date());

  for (const file of files) {
    const name = encoder.encode(file.path);
    const crc = crc32(file.content);
    const local = new Uint8Array(30 + name.length);
    const localView = new DataView(local.buffer);
    localView.setUint32(0, 0x04034b50, true);
    localView.setUint16(4, 20, true);
    localView.setUint16(10, dosTime, true);
    localView.setUint16(12, dosDate, true);
    localView.setUint32(14, crc, true);
    localView.setUint32(18, file.content.length, true);
    localView.setUint32(22, file.content.length, true);
    localView.setUint16(26, name.length, true);
    local.set(name, 30);
    localParts.push(local, file.content);

    const central = new Uint8Array(46 + name.length);
    const centralView = new DataView(central.buffer);
    centralView.setUint32(0, 0x02014b50, true);
    centralView.setUint16(4, 20, true);
    centralView.setUint16(6, 20, true);
    centralView.setUint16(12, dosTime, true);
    centralView.setUint16(14, dosDate, true);
    centralView.setUint32(16, crc, true);
    centralView.setUint32(20, file.content.length, true);
    centralView.setUint32(24, file.content.length, true);
    centralView.setUint16(28, name.length, true);
    centralView.setUint32(42, offset, true);
    central.set(name, 46);
    centralParts.push(central);

    offset += local.length + file.content.length;
  }

  const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0);
  const end = new Uint8Array(22);
  const endView = new DataView(end.buffer);
  endView.setUint32(0, 0x06054b50, true);
  endView.setUint16(8, files.length, true);
  endView.setUint16(10, files.length, true);
  endView.setUint32(12, centralSize, true);
  endView.setUint32(16, offset, true);

  return concatBytes([...localParts, ...centralParts, end]);
}

function zipDate(date: Date) {
  const dosTime =
    (date.getHours() << 11) | (date.getMinutes() << 5) | Math.floor(date.getSeconds() / 2);
  const dosDate =
    ((date.getFullYear() - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate();
  return { dosTime, dosDate };
}

function concatBytes(parts: Uint8Array[]) {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const output = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.length;
  }
  return output;
}

function crc32(bytes: Uint8Array) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let index = 0; index < 8; index += 1) {
      crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}
