import { useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, Check, LoaderCircle, X } from "lucide-react";

import { updateTableContent } from "../api/reportApi";
import type {
  ColumnDefinition,
  StatTable,
  StatTablePart,
  TableContentUpdatePayload,
  TableMetadata,
} from "../types";
import { formatCellValue } from "../utils/formatters";
import { DownloadMenu } from "./DownloadMenu";
import { StatusBadge } from "./StatusBadge";

interface TableEditViewProps {
  table: StatTable;
  reportId: number;
  accessToken: string;
  onCancel: () => void;
  onSaved: (table: StatTable) => void;
}

export function TableEditView({
  table,
  reportId,
  accessToken,
  onCancel,
  onSaved,
}: TableEditViewProps) {
  const [draft, setDraft] = useState<StatTable>(() => cloneTable(table));
  const parts = useMemo(() => editableParts(draft), [draft]);
  const [activePartId, setActivePartId] = useState(parts[0]?.id ?? draft.id);
  const activePart = parts.find((part) => part.id === activePartId) ?? parts[0];
  const [stickyHeader, setStickyHeader] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const dirty = JSON.stringify(draft) !== JSON.stringify(table);
  const parentHierarchy = draft.hierarchy.slice(0, -1);

  function updatePage(values: Partial<StatTable>) {
    setDraft((current) => ({ ...current, ...values }));
  }

  function updateHierarchy(
    index: number,
    values: { code: string; title: string; title_en: string },
  ) {
    setDraft((current) => {
      const item = current.hierarchy[index];
      if (!item) {
        return current;
      }
      const hierarchy = current.hierarchy.map((entry, entryIndex) => {
        if (entryIndex === index) {
          return { ...entry, ...values };
        }
        return entryIndex > index
          ? { ...entry, code: replaceCodePrefix(entry.code, item.code, values.code) }
          : entry;
      });
      const domainLevel = isDomainHierarchyItem(item.code, current.code);
      const code = replaceCodePrefix(current.code, item.code, values.code);
      return {
        ...current,
        code,
        hierarchy,
        ...(domainLevel
          ? { domain: values.title }
          : { section_title: values.title, section_title_en: values.title_en }),
      };
    });
  }

  function updatePart(update: (part: StatTablePart) => StatTablePart) {
    setDraft((current) => {
      if (current.parts.length === 0) {
        const next = update(rootTableAsPart(current));
        return {
          ...current,
          unit: next.unit,
          columns: next.columns,
          rows: next.rows,
          metadata: next.metadata,
        };
      }
      return {
        ...current,
        parts: current.parts.map((part) =>
          part.id === activePart.id ? update(part) : part,
        ),
      };
    });
  }

  async function save() {
    if (saving) {
      return;
    }
    if (!dirty) {
      onCancel();
      return;
    }
    setSaving(true);
    setError("");
    try {
      const updated = await updateTableContent(
        reportId,
        table.id,
        accessToken,
        buildTableUpdatePayload(table, draft),
      );
      onSaved(updated);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "수정한 연보를 저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  function cancel() {
    if (!dirty || window.confirm("저장하지 않은 수정 내용을 버리고 상세 페이지로 돌아갈까요?")) {
      onCancel();
    }
  }

  return (
    <main className="detail-view table-edit-view">
      <header className="detail-header">
        <button className="icon-button" type="button" onClick={cancel} aria-label="수정 취소">
          <ArrowLeft aria-hidden="true" size={19} />
        </button>
        <div className={`detail-title detail-title--${draft.theme}`}>
          <div className="detail-title__body">
            <div className="detail-title__meta">
              <InlineEditField
                ariaLabel="표 번호 수정"
                value={draft.code}
                onChange={(value) => updatePage({ code: value })}
                triggerClassName="detail-title__code editable-title-trigger"
              >
                {draft.code}
              </InlineEditField>
              {parentHierarchy.map((item, index) => (
                <HierarchyEditField
                  code={item.code}
                  key={`${item.code}-${item.title}`}
                  title={item.title}
                  titleEn={item.title_en ?? ""}
                  showEnglish={!isDomainHierarchyItem(item.code, draft.code)}
                  onChange={(values) => updateHierarchy(index, values)}
                >
                  <span className="detail-title__crumb">
                    {item.code ? <em>{item.code}</em> : null}
                    <strong>{item.title}</strong>
                  </span>
                </HierarchyEditField>
              ))}
            </div>
            <h1>
              <InlineEditField
                ariaLabel="표 제목 수정"
                value={draft.title}
                onChange={(value) => updatePage({ title: value })}
                triggerClassName="editable-heading-trigger"
              >
                {draft.title}
              </InlineEditField>
            </h1>
            <p>
              <InlineEditField
                ariaLabel="영문 제목 수정"
                value={draft.title_en}
                onChange={(value) => updatePage({ title_en: value })}
                triggerClassName="editable-subtitle-trigger"
              >
                {draft.title_en || "영문 제목 없음"}
              </InlineEditField>
            </p>
          </div>
        </div>
        <div className="detail-header__actions">
          <StatusBadge status={draft.status} label={draft.status_label} />
          <span className="edit-mode-badge">수정 중</span>
          <button
            className="primary-button"
            type="button"
            disabled={saving || !draft.code.trim() || !draft.title.trim()}
            onClick={() => void save()}
          >
            {saving ? (
              <LoaderCircle className="is-spinning" aria-hidden="true" size={16} />
            ) : (
              <Check aria-hidden="true" size={16} />
            )}
            {saving ? "저장 중" : "완료"}
          </button>
          <DownloadMenu table={draft} />
        </div>
      </header>

      <div className="detail-meta-strip editable-meta-strip">
        <span>
          <em>기준일</em>
          <InlineEditField
            ariaLabel="기준일 수정"
            value={activePart.metadata.base_date}
            onChange={(value) => updateMetadata(updatePart, { base_date: value })}
          >
            <strong>{activePart.metadata.base_date || "-"}</strong>
          </InlineEditField>
        </span>
        <span>
          <em>단위</em>
          <InlineEditField
            ariaLabel="단위 수정"
            value={activePart.unit}
            onChange={(value) =>
              updatePart((part) => ({
                ...part,
                unit: value,
                metadata: { ...part.metadata, unit_display: value },
              }))
            }
          >
            <strong>{activePart.unit || "-"}</strong>
          </InlineEditField>
        </span>
        {parts.length > 1 ? (
          <span>
            <em>하위 표</em>
            <strong>{parts.length}개</strong>
          </span>
        ) : null}
        <span>
          <em>최종 수정일</em>
          <strong>{activePart.updated_at}</strong>
        </span>
      </div>

      {error ? <div className="edit-save-error">{error}</div> : null}

      <div className="detail-workspace">
        <aside className="original-table-panel">
          <div className="detail-section detail-section--original">
            <div className="content-title-row">
              <div className="original-title-group">
                <h2>원본 표</h2>
                {parts.length > 1 ? (
                  <div className="part-tabs" aria-label="하위 표 선택">
                    {parts.map((part) => (
                      <button
                        className={activePart.id === part.id ? "is-active" : ""}
                        key={part.id}
                        type="button"
                        onClick={() => setActivePartId(part.id)}
                      >
                        <span>{part.part_label}</span>
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
              <label className="table-option-toggle">
                <input
                  checked={stickyHeader}
                  onChange={(event) => setStickyHeader(event.target.checked)}
                  type="checkbox"
                />
                <span>헤더 고정</span>
              </label>
            </div>
            <EditableDataGrid
              columns={activePart.columns}
              rows={activePart.rows}
              theme={draft.theme}
              stickyHeader={stickyHeader}
              onColumnsChange={(columns) => updatePart((part) => ({ ...part, columns }))}
              onRowsChange={(rows) => updatePart((part) => ({ ...part, rows }))}
            />
          </div>
        </aside>

        <section className="detail-analysis-panel" aria-label="메타데이터 수정">
          <div className="detail-tabs">
            <button className="is-active" type="button">메타데이터</button>
          </div>
          <section className="detail-content">
            <div className="detail-section">
              <div className="content-title-row">
                <div>
                  <h2>출처·메타정보</h2>
                </div>
              </div>
              <EditableMetadataGrid
                table={draft}
                part={activePart}
                updatePage={updatePage}
                updatePart={updatePart}
              />
            </div>
          </section>
        </section>
      </div>
    </main>
  );
}

function InlineEditField({
  ariaLabel,
  value,
  onChange,
  children,
  multiline = false,
  triggerClassName = "",
}: {
  ariaLabel: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
  multiline?: boolean;
  triggerClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const [draftValue, setDraftValue] = useState(value);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

  function openEditor(trigger: HTMLElement) {
    setDraftValue(value);
    setAnchor(trigger);
    setOpen(true);
  }

  function apply() {
    onChange(draftValue);
    setOpen(false);
    setAnchor(null);
  }

  function cancel() {
    setDraftValue(value);
    setOpen(false);
    setAnchor(null);
  }

  return (
    <span className="inline-edit-field">
      <button
        className={`inline-edit-trigger ${triggerClassName}`.trim()}
        type="button"
        aria-label={ariaLabel}
        onClick={(event) => openEditor(event.currentTarget)}
      >
        {children}
      </button>
      {open ? (
        <InlineEditPopover
          ariaLabel={ariaLabel}
          anchor={anchor}
          multiline={multiline}
          value={draftValue}
          onChange={setDraftValue}
          onApply={apply}
          onCancel={cancel}
        />
      ) : null}
    </span>
  );
}

function InlineEditPopover({
  ariaLabel,
  anchor,
  multiline,
  value,
  onChange,
  onApply,
  onCancel,
}: {
  ariaLabel: string;
  anchor: HTMLElement | null;
  multiline: boolean;
  value: string;
  onChange: (value: string) => void;
  onApply: () => void;
  onCancel: () => void;
}) {
  const [position, setPosition] = useState({ left: 0, top: 0 });

  useLayoutEffect(() => {
    if (!anchor) {
      return;
    }

    const updatePosition = () => {
      const rect = anchor.getBoundingClientRect();
      const width = Math.min(470, window.innerWidth - 32);
      const estimatedHeight = multiline ? 160 : 68;
      setPosition({
        left: clamp(rect.left, 16, window.innerWidth - width - 16),
        top: clamp(rect.bottom + 7, 16, window.innerHeight - estimatedHeight - 16),
      });
    };

    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [anchor, multiline]);

  if (!anchor) {
    return null;
  }

  return createPortal(
    <span className="inline-edit-popover" style={position}>
      <span className="edit-popover__field">
        {multiline ? (
          <textarea
            autoFocus
            rows={4}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                onCancel();
              }
            }}
          />
        ) : (
          <input
            autoFocus
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                onApply();
              }
              if (event.key === "Escape") {
                onCancel();
              }
            }}
          />
        )}
      </span>
      <span className="edit-popover__actions">
        <button className="inline-edit-popover__done" type="button" onClick={onApply}>
          적용
        </button>
        <button className="edit-popover__close" type="button" aria-label={`${ariaLabel} 닫기`} onClick={onCancel}>
          <X aria-hidden="true" size={18} />
        </button>
      </span>
    </span>,
    document.body,
  );
}

function HierarchyEditField({
  code,
  title,
  titleEn,
  showEnglish,
  onChange,
  children,
}: {
  code: string;
  title: string;
  titleEn: string;
  showEnglish: boolean;
  onChange: (values: { code: string; title: string; title_en: string }) => void;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  return (
    <span className="inline-edit-field">
      <button
        className="inline-edit-trigger"
        type="button"
        aria-label={`${title} 대제목 수정`}
        onClick={(event) => {
          setAnchor(event.currentTarget);
          setOpen(true);
        }}
      >
        {children}
      </button>
      {open ? (
        <GridEditPopover
          label={`${title} 대제목 수정`}
          code={code}
          value={title}
          valueEn={titleEn}
          footnote=""
          anchor={anchor}
          showCode
          showEnglish={showEnglish}
          showFootnote={false}
          onApply={(values) => {
            onChange({ code: values.code ?? code, title: values.value, title_en: values.valueEn });
            setOpen(false);
            setAnchor(null);
          }}
          onCancel={() => {
            setOpen(false);
            setAnchor(null);
          }}
        />
      ) : null}
    </span>
  );
}

function EditableDataGrid({
  columns,
  rows,
  theme,
  stickyHeader,
  onColumnsChange,
  onRowsChange,
}: {
  columns: ColumnDefinition[];
  rows: Array<Record<string, string | number>>;
  theme: StatTable["theme"];
  stickyHeader: boolean;
  onColumnsChange: (columns: ColumnDefinition[]) => void;
  onRowsChange: (rows: Array<Record<string, string | number>>) => void;
}) {
  const [activeEditor, setActiveEditor] = useState<string | null>(null);
  const [editorAnchor, setEditorAnchor] = useState<HTMLElement | null>(null);

  function openEditor(editorKey: string, trigger: HTMLElement) {
    const cell = trigger.closest("th, td");
    setEditorAnchor(cell instanceof HTMLElement ? cell : null);
    setActiveEditor(editorKey);
  }

  function closeEditor() {
    setActiveEditor(null);
    setEditorAnchor(null);
  }

  function updateColumn(index: number, values: Partial<ColumnDefinition>) {
    onColumnsChange(
      columns.map((column, columnIndex) =>
        columnIndex === index ? { ...column, ...values } : column,
      ),
    );
  }

  function updateRow(index: number, key: string, value: string) {
    updateRowValues(index, { [key]: value });
  }

  function updateRowValues(index: number, values: Record<string, string>) {
    onRowsChange(
      rows.map((row, rowIndex) =>
        rowIndex === index ? { ...row, ...values } : row,
      ),
    );
  }

  return (
    <div
      className={[
        "data-grid",
        "editable-data-grid",
        `data-grid--${theme}`,
        stickyHeader ? "data-grid--sticky-header" : "",
      ].filter(Boolean).join(" ")}
    >
      <table>
        <colgroup>
          {columns.map((column) => (
            <col key={column.key} style={column.width ? { width: column.width } : undefined} />
          ))}
        </colgroup>
        <thead>
          <tr>
            {columns.map((column, columnIndex) => {
              const editorKey = `header-${columnIndex}-${column.key}`;
              return (
                <th key={column.key} className={`align-${column.align}`}>
                  <button
                    className="editable-grid-trigger"
                    type="button"
                    aria-label={`${column.label} 헤더 수정`}
                    onClick={(event) => openEditor(editorKey, event.currentTarget)}
                  >
                    <span>
                      {column.label}
                      {column.footnote_marker ? (
                        <sup className="data-grid__footnote">{column.footnote_marker}</sup>
                      ) : null}
                    </span>
                    {column.label_en ? <small>{column.label_en}</small> : null}
                  </button>
                  {activeEditor === editorKey ? (
                    <GridEditPopover
                      label="헤더 수정"
                      value={column.label}
                      valueEn={column.label_en ?? ""}
                      footnote={column.footnote_marker ?? ""}
                      anchor={editorAnchor}
                      onApply={(values) => {
                        updateColumn(columnIndex, {
                          label: values.value,
                          label_en: values.valueEn,
                          footnote_marker: values.footnote,
                        });
                        closeEditor();
                      }}
                      onCancel={closeEditor}
                    />
                  ) : null}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => {
            const firstColumnKey = columns[0]?.key;
            const summaryKind = summaryRowKind(row, firstColumnKey);
            return (
              <tr
                className={
                  summaryKind === "total"
                    ? "data-grid__summary-row"
                    : summaryKind === "subtotal"
                      ? "data-grid__subtotal-row"
                      : ""
                }
                key={`${row._row_index ?? rowIndex}-${rowIndex}`}
              >
                {columns.map((column) => {
                  const editorKey = `cell-${rowIndex}-${column.key}`;
                  const value = String(row[column.key] ?? "");
                  const valueEn = String(row[`${column.key}_en`] ?? "");
                  const footnote = String(row[`${column.key}_footnote`] ?? "");
                  return (
                    <td key={column.key} className={`align-${column.align}`}>
                      <button
                        className="editable-grid-trigger"
                        type="button"
                        aria-label={`${rowIndex + 1}행 ${column.label} 수정`}
                        onClick={(event) => openEditor(editorKey, event.currentTarget)}
                      >
                        <span>
                          {formatCellValue(row[column.key] ?? "", column.label)}
                          {footnote ? <sup className="data-grid__footnote">{footnote}</sup> : null}
                        </span>
                        {valueEn ? <small>{valueEn}</small> : null}
                      </button>
                      {activeEditor === editorKey ? (
                        <GridEditPopover
                          label={`${rowIndex + 1}행 · ${column.label}`}
                          value={value}
                          valueEn={valueEn}
                          footnote={footnote}
                          anchor={editorAnchor}
                          onApply={(values) => {
                            updateRowValues(rowIndex, {
                              [column.key]: values.value,
                              [`${column.key}_en`]: values.valueEn,
                              [`${column.key}_footnote`]: values.footnote,
                            });
                            closeEditor();
                          }}
                          onCancel={closeEditor}
                        />
                      ) : null}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function GridEditPopover({
  label,
  code = "",
  value,
  valueEn,
  footnote,
  anchor,
  showCode = false,
  showEnglish = true,
  showFootnote = true,
  onApply,
  onCancel,
}: {
  label: string;
  code?: string;
  value: string;
  valueEn: string;
  footnote: string;
  anchor: HTMLElement | null;
  showCode?: boolean;
  showEnglish?: boolean;
  showFootnote?: boolean;
  onApply: (values: { code?: string; value: string; valueEn: string; footnote: string }) => void;
  onCancel: () => void;
}) {
  const [position, setPosition] = useState({ left: 0, top: 0 });
  const [draftCode, setDraftCode] = useState(code);
  const [draftValue, setDraftValue] = useState(value);
  const [draftValueEn, setDraftValueEn] = useState(valueEn);
  const [draftFootnote, setDraftFootnote] = useState(footnote);

  useLayoutEffect(() => {
    if (!anchor) {
      return;
    }

    const updatePosition = () => {
      const rect = anchor.getBoundingClientRect();
      const width = Math.min(330, window.innerWidth - 32);
      const estimatedHeight = 330;
      setPosition({
        left: clamp(rect.left, 16, window.innerWidth - width - 16),
        top: clamp(rect.bottom + 6, 16, window.innerHeight - estimatedHeight - 16),
      });
    };

    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [anchor]);

  useLayoutEffect(() => {
    setDraftCode(code);
    setDraftValue(value);
    setDraftValueEn(valueEn);
    setDraftFootnote(footnote);
  }, [code, value, valueEn, footnote]);

  if (!anchor) {
    return null;
  }

  return createPortal(
    <div className="grid-edit-popover" style={position}>
      <div className="edit-popover__fields">
        {showCode ? (
          <label>
            <span>번호</span>
            <input value={draftCode} onChange={(event) => setDraftCode(event.target.value)} />
          </label>
        ) : null}
        <label>
          <span>표시값</span>
          <input autoFocus value={draftValue} onChange={(event) => setDraftValue(event.target.value)} />
        </label>
        {showEnglish ? (
          <label>
            <span>영문값</span>
            <input value={draftValueEn} onChange={(event) => setDraftValueEn(event.target.value)} />
          </label>
        ) : null}
        {showFootnote ? (
          <label className="grid-edit-popover__footnote">
            <span>각주</span>
            <input value={draftFootnote} onChange={(event) => setDraftFootnote(event.target.value)} />
          </label>
        ) : null}
      </div>
      <div className="edit-popover__actions">
        <button
          className="inline-edit-popover__done"
          type="button"
          onClick={() =>
            onApply({
              code: showCode ? draftCode : undefined,
              value: draftValue,
              valueEn: draftValueEn,
              footnote: draftFootnote,
            })
          }
        >
          적용
        </button>
        <button className="edit-popover__close" type="button" aria-label={`${label} 닫기`} onClick={onCancel}>
          <X aria-hidden="true" size={18} />
        </button>
      </div>
    </div>,
    document.body,
  );
}

function EditableMetadataGrid({
  table,
  part,
  updatePage,
  updatePart,
}: {
  table: StatTable;
  part: StatTablePart;
  updatePage: (values: Partial<StatTable>) => void;
  updatePart: (update: (part: StatTablePart) => StatTablePart) => void;
}) {
  return (
    <dl className="metadata-grid editable-metadata-grid">
      <MetadataField label="기준일" value={part.metadata.base_date} onChange={(value) => updateMetadata(updatePart, { base_date: value })} />
      <MetadataField label="단위" value={part.unit} onChange={(value) => updatePart((current) => ({ ...current, unit: value, metadata: { ...current.metadata, unit_display: value } }))} />
      <div>
        <dt>최종 수정 일자</dt>
        <dd>{part.updated_at}</dd>
      </div>
      <MetadataField label="소속" value={part.metadata.source_department} onChange={(value) => updateMetadata(updatePart, { source_department: value })} />
      <MetadataField label="이름" value={part.metadata.source_officer} onChange={(value) => updateMetadata(updatePart, { source_officer: value })} />
      <MetadataField label="내선번호" value={part.metadata.source_extension} onChange={(value) => updateMetadata(updatePart, { source_extension: value })} />
      <MetadataField wide label="출처" value={part.metadata.source_reference} multiline onChange={(value) => updateMetadata(updatePart, { source_reference: value })} />
      <MetadataField wide label="주석" value={part.metadata.note} multiline onChange={(value) => updateMetadata(updatePart, { note: value })} />
    </dl>
  );
}

function MetadataField({
  label,
  value,
  onChange,
  wide = false,
  multiline = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  wide?: boolean;
  multiline?: boolean;
}) {
  return (
    <div className={wide ? "metadata-grid__wide" : ""}>
      <dt>{label}</dt>
      <dd>
        <InlineEditField
          ariaLabel={`${label} 수정`}
          value={value}
          multiline={multiline}
          onChange={onChange}
          triggerClassName="editable-metadata-trigger"
        >
          {value || "-"}
        </InlineEditField>
      </dd>
    </div>
  );
}

function updateMetadata(
  updatePart: (update: (part: StatTablePart) => StatTablePart) => void,
  values: Partial<TableMetadata>,
) {
  updatePart((part) => ({ ...part, metadata: { ...part.metadata, ...values } }));
}

function summaryRowKind(row: Record<string, string | number>, firstColumnKey?: string) {
  const label = String(row._row_label ?? (firstColumnKey ? row[firstColumnKey] : "") ?? "")
    .replace(/[\s·,._-]/g, "")
    .toLowerCase();
  if (label.startsWith("소계") || label.includes("subtotal")) {
    return "subtotal";
  }
  return ["계", "합계", "총계", "total", "grandtotal"].includes(label) ? "total" : undefined;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(value, max));
}

function editableParts(table: StatTable): StatTablePart[] {
  return table.parts.length > 0 ? table.parts : [rootTableAsPart(table)];
}

function rootTableAsPart(table: StatTable): StatTablePart {
  return {
    id: table.id,
    code: table.code,
    title: table.title,
    title_en: table.title_en,
    part_label: "원본 표",
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
    validation_stale: table.validation_stale,
  };
}

function cloneTable(table: StatTable): StatTable {
  return JSON.parse(JSON.stringify(table)) as StatTable;
}

export function buildTableUpdatePayload(
  original: StatTable,
  draft: StatTable,
): TableContentUpdatePayload {
  const originalParts = editableParts(original);
  const draftParts = editableParts(draft);
  return {
    code: draft.code.trim(),
    title: draft.title.trim(),
    title_en: draft.title_en.trim(),
    section_title: draft.section_title.trim(),
    section_title_en: draft.section_title_en.trim(),
    domain: draft.domain.trim(),
    hierarchy_patches: original.hierarchy.slice(0, -1).flatMap((item, index) => {
      const next = draft.hierarchy[index];
      if (!next) {
        return [];
      }
      const titleEn = item.title_en ?? "";
      const nextTitleEn = next.title_en ?? "";
      if (
        item.code === next.code &&
        item.title === next.title &&
        titleEn === nextTitleEn
      ) {
        return [];
      }
      return [{
        kind: isDomainHierarchyItem(item.code, original.code) ? "domain" as const : "section" as const,
        original_code: item.code,
        code: next.code.trim(),
        title: next.title.trim(),
        title_en: nextTitleEn.trim(),
      }];
    }),
    parts: draftParts.map((part, partIndex) => {
      const baseline = originalParts.find((item) => item.id === part.id) ?? originalParts[partIndex];
      const suffix = original.parts.length > 0
        ? (part.code.match(/\s+표\s*\d+$/)?.[0] ?? ` 표${partIndex + 1}`)
        : "";
      const columns = part.columns.flatMap((column) => {
        const previous = baseline.columns.find((item) => item.key === column.key);
        if (
          previous &&
          previous.label === column.label &&
          (previous.label_en ?? "") === (column.label_en ?? "") &&
          (previous.footnote_marker ?? "") === (column.footnote_marker ?? "")
        ) {
          return [];
        }
        return [{
          source_col_indexes: sourceColumnIndexes(column),
          label: column.label,
          label_en: column.label_en ?? "",
          footnote_marker: column.footnote_marker ?? "",
        }];
      });
      const cells = part.rows.flatMap((row, rowIndex) => {
        const sourceRowIndex = Number(row._row_index ?? (part.metadata.header_count ?? 0) + rowIndex);
        const previousRow = baseline.rows.find(
          (item) => Number(item._row_index) === sourceRowIndex,
        ) ?? baseline.rows[rowIndex] ?? {};
        return part.columns.flatMap((column, columnIndex) => {
          const value = String(row[column.key] ?? "");
          const valueEn = String(row[`${column.key}_en`] ?? "");
          const footnote = String(row[`${column.key}_footnote`] ?? "");
          if (
            value === String(previousRow[column.key] ?? "") &&
            valueEn === String(previousRow[`${column.key}_en`] ?? "") &&
            footnote === String(previousRow[`${column.key}_footnote`] ?? "")
          ) {
            return [];
          }
          const indexes = sourceColumnIndexes(column);
          const targetIndex = columnIndex === 0 ? indexes[indexes.length - 1] : indexes[0];
          return [{
            row_index: sourceRowIndex,
            col_index: targetIndex,
            value,
            value_en: valueEn,
            footnote_marker: footnote,
          }];
        });
      });
      return {
        id: part.id,
        code: `${draft.code.trim()}${suffix}`,
        title: `${draft.title.trim()}${suffix}`,
        title_en: draft.title_en.trim(),
        unit: part.unit,
        header_count: part.metadata.header_count ?? 0,
        metadata: {
          base_date: part.metadata.base_date,
          note: part.metadata.note,
          source: part.metadata.source,
          source_department: part.metadata.source_department,
          source_officer: part.metadata.source_officer,
          source_extension: part.metadata.source_extension,
          source_reference: part.metadata.source_reference,
        },
        columns,
        cells,
      };
    }),
  };
}

function isDomainHierarchyItem(hierarchyCode: string, tableCode: string): boolean {
  return hierarchyCode === baseCode(tableCode).split("-", 1)[0];
}

function replaceCodePrefix(code: string, oldPrefix: string, nextPrefix: string): string {
  if (code === oldPrefix) {
    return nextPrefix;
  }
  if (code.startsWith(`${oldPrefix}-`) || code.startsWith(`${oldPrefix} 표`)) {
    return `${nextPrefix}${code.slice(oldPrefix.length)}`;
  }
  return code;
}

function baseCode(code: string): string {
  return code.replace(/\s+표\s*\d+$/, "");
}

function sourceColumnIndexes(column: ColumnDefinition): number[] {
  if (column.source_col_indexes?.length) {
    return column.source_col_indexes;
  }
  if (typeof column.source_col_index === "number") {
    return [column.source_col_index];
  }
  const parsed = Number(column.key.replace(/^c/, ""));
  return Number.isFinite(parsed) ? [parsed] : [0];
}
