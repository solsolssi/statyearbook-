import {
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, Check, LoaderCircle, Plus, Trash2, X } from "lucide-react";

import { cloneStatistic, deleteStatistic, updateTableContent } from "../api/reportApi";
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
import { headerLayout } from "../utils/headerLayout";

interface TableEditViewProps {
  table: StatTable;
  reportId: number;
  accessToken: string;
  onCancel: () => void;
  onSaved: (table: StatTable) => void;
  onCreated?: (table: StatTable) => void;
  onDeleted?: () => void;
}

export function TableEditView({
  table,
  reportId,
  accessToken,
  onCancel,
  onSaved,
  onCreated,
  onDeleted,
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

  async function addStatistic() {
    if (dirty && !window.confirm("저장하지 않은 수정은 새 통계에 반영되지 않습니다. 계속할까요?")) {
      return;
    }
    const code = window.prompt("추가할 통계 번호를 입력해 주세요.", "");
    if (!code?.trim()) {
      return;
    }
    const title = window.prompt("추가할 통계 제목을 입력해 주세요.", `${table.title} 복사본`);
    if (!title?.trim()) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      const created = await cloneStatistic(reportId, table.id, accessToken, code.trim(), title.trim());
      onCreated?.(created);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "통계를 추가하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  async function removeStatistic() {
    if (!window.confirm(`‘${table.code} ${table.title}’ 통계를 연보에서 삭제할까요?`)) {
      return;
    }
    setSaving(true);
    setError("");
    try {
      await deleteStatistic(reportId, table.id, accessToken);
      onDeleted?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "통계를 삭제하지 못했습니다.");
    } finally {
      setSaving(false);
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
          <button className="secondary-button table-edit-structure-button" type="button" disabled={saving} onClick={() => void addStatistic()}>
            <Plus aria-hidden="true" size={15} /> 통계 추가
          </button>
          <button className="secondary-button table-edit-delete-button" type="button" disabled={saving} onClick={() => void removeStatistic()}>
            <Trash2 aria-hidden="true" size={15} /> 통계 삭제
          </button>
          <button
            className="secondary-button table-edit-cancel-button"
            type="button"
            disabled={saving}
            onClick={cancel}
          >
            <X aria-hidden="true" size={15} /> 취소
          </button>
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
  const [dragging, setDragging] = useState<{ kind: "row" | "column"; index: number } | null>(null);
  const [dragOver, setDragOver] = useState<{ kind: "row" | "column"; index: number } | null>(null);
  const [edgeTrimPreview, setEdgeTrimPreview] = useState<{
    kind: "row" | "column";
    keepCount: number;
  } | null>(null);
  const edgeGesture = useRef<{
    kind: "row" | "column";
    pointerId: number;
    startX: number;
    startY: number;
    moved: boolean;
    keepCount: number;
  } | null>(null);
  const suppressEdgeClick = useRef(false);
  const headers = headerLayout(columns);

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

  function updateColumnHeader(
    index: number,
    values: { label: string; labelEn: string; parentPath: string; parentPathEn: string; footnote: string },
  ) {
    const path = [...splitHeaderPath(values.parentPath), values.label.trim()].filter(Boolean);
    const pathEn = [...splitHeaderPath(values.parentPathEn), values.labelEn.trim()].filter(Boolean);
    const previousParent = headerParentPath(columns[index]);
    const previousParentEn = headerParentPathEn(columns[index]);
    onColumnsChange(columns.map((column, columnIndex) => {
      const sharesParent = previousParent.length > 0 &&
        JSON.stringify(headerParentPath(column)) === JSON.stringify(previousParent);
      if (columnIndex !== index && !sharesParent) {
        return column;
      }
      const leaf = columnIndex === index ? values.label.trim() : headerLeaf(column);
      const leafEn = columnIndex === index ? values.labelEn.trim() : headerLeafEn(column);
      const nextPath = [...splitHeaderPath(values.parentPath), leaf].filter(Boolean);
      const nextPathEn = [
        ...(
          previousParentEn.length > 0 || columnIndex === index
            ? splitHeaderPath(values.parentPathEn)
            : headerParentPathEn(column)
        ),
        leafEn,
      ].filter(Boolean);
      return {
        ...column,
        label: nextPath.join(" / ") || leaf,
        label_en: nextPathEn.join(" / "),
        header_path: nextPath,
        header_path_en: nextPathEn,
        ...(columnIndex === index ? { footnote_marker: values.footnote } : {}),
      };
    }));
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

  function addColumn() {
    const parentPathInput = window.prompt(
      "상위 헤더를 입력해 주세요. 여러 단계는 /로 구분합니다. (예: 방문 발급 / 국내)",
      "",
    );
    if (parentPathInput === null) return;
    const label = window.prompt("새 열 이름을 입력해 주세요.", "새 열");
    if (!label?.trim()) return;
    const parentPathEnInput = window.prompt("상위 영문 헤더를 입력해 주세요. 없으면 비워 두세요.", "");
    if (parentPathEnInput === null) return;
    const labelEn = window.prompt("새 열의 영문 이름을 입력해 주세요. 없으면 비워 두세요.", "");
    if (labelEn === null) return;
    const headerPath = [...splitHeaderPath(parentPathInput), label.trim()];
    const headerPathEn = [...splitHeaderPath(parentPathEnInput), labelEn.trim()].filter(Boolean);
    const key = `new_column_${Date.now()}`;
    onColumnsChange([
      ...columns,
      {
        key,
        label: headerPath.join(" / "),
        label_en: headerPathEn.join(" / "),
        header_path: headerPath,
        header_path_en: headerPathEn,
        align: "right",
        source_col_index: columns.length,
        source_col_indexes: [columns.length],
      },
    ]);
  }

  function removeColumn(index: number) {
    if (columns.length <= 1) {
      window.alert("표에는 열이 한 개 이상 있어야 합니다.");
      return;
    }
    onColumnsChange(columns.filter((_, columnIndex) => columnIndex !== index));
  }

  function addRow() {
    const row: Record<string, string | number> = {
      _row_index: -Date.now(),
      _row_label: "",
    };
    for (const column of columns) {
      row[column.key] = "";
    }
    onRowsChange([...rows, row]);
  }

  function removeRow(index: number) {
    onRowsChange(rows.filter((_, rowIndex) => rowIndex !== index));
  }

  function startDrag(
    event: DragEvent<HTMLElement>,
    kind: "row" | "column",
    index: number,
  ) {
    closeEditor();
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", `${kind}:${index}`);
    setDragging({ kind, index });
    setDragOver(null);
  }

  function finishDrag() {
    setDragging(null);
    setDragOver(null);
  }

  function dropAt(kind: "row" | "column", index: number) {
    if (!dragging || dragging.kind !== kind || dragging.index === index) {
      finishDrag();
      return;
    }
    if (kind === "column") {
      const next = [...columns];
      const [moved] = next.splice(dragging.index, 1);
      next.splice(index, 0, moved);
      onColumnsChange(next);
    } else {
      const next = [...rows];
      const [moved] = next.splice(dragging.index, 1);
      next.splice(index, 0, moved);
      onRowsChange(next);
    }
    finishDrag();
  }

  function dropToDelete() {
    if (!dragging) {
      return;
    }
    if (dragging.kind === "column") {
      removeColumn(dragging.index);
    } else {
      removeRow(dragging.index);
    }
    finishDrag();
  }

  function startEdgeResize(
    event: ReactPointerEvent<HTMLButtonElement>,
    kind: "row" | "column",
  ) {
    closeEditor();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const keepCount = kind === "row" ? rows.length : columns.length;
    edgeGesture.current = {
      kind,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
      keepCount,
    };
    setEdgeTrimPreview({ kind, keepCount });
  }

  function updateEdgeResize(
    event: ReactPointerEvent<HTMLButtonElement>,
    kind: "row" | "column",
  ) {
    const gesture = edgeGesture.current;
    if (!gesture || gesture.kind !== kind || gesture.pointerId !== event.pointerId) {
      return;
    }
    const inwardDistance = kind === "row"
      ? gesture.startY - event.clientY
      : gesture.startX - event.clientX;
    if (inwardDistance < 4) {
      return;
    }
    gesture.moved = true;
    const table = event.currentTarget.parentElement?.querySelector("table");
    if (!(table instanceof HTMLTableElement)) {
      return;
    }

    if (kind === "row") {
      const rowElements = Array.from(table.tBodies[0]?.rows ?? []);
      const keepCount = rowElements.filter(
        (rowElement) => {
          const rect = rowElement.getBoundingClientRect();
          return event.clientY > rect.top + rect.height / 2;
        },
      ).length;
      gesture.keepCount = keepCount;
      setEdgeTrimPreview({ kind, keepCount });
      return;
    }

    const columnElements = Array.from(table.tHead?.rows[0]?.cells ?? []);
    const keepCount = Math.max(
      1,
      columnElements.filter(
        (columnElement) => {
          const rect = columnElement.getBoundingClientRect();
          return event.clientX > rect.left + rect.width / 2;
        },
      ).length,
    );
    gesture.keepCount = keepCount;
    setEdgeTrimPreview({ kind, keepCount });
  }

  function finishEdgeResize(
    event: ReactPointerEvent<HTMLButtonElement>,
    kind: "row" | "column",
  ) {
    const gesture = edgeGesture.current;
    if (!gesture || gesture.kind !== kind || gesture.pointerId !== event.pointerId) {
      return;
    }
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    if (gesture.moved) {
      suppressEdgeClick.current = true;
      window.setTimeout(() => {
        suppressEdgeClick.current = false;
      }, 0);
      if (kind === "row" && gesture.keepCount < rows.length) {
        onRowsChange(rows.slice(0, gesture.keepCount));
      }
      if (kind === "column" && gesture.keepCount < columns.length) {
        onColumnsChange(columns.slice(0, gesture.keepCount));
      }
    }
    edgeGesture.current = null;
    setEdgeTrimPreview(null);
  }

  function cancelEdgeResize() {
    edgeGesture.current = null;
    setEdgeTrimPreview(null);
  }

  function clickEdgeAdd(kind: "row" | "column") {
    if (suppressEdgeClick.current) {
      return;
    }
    if (kind === "row") {
      addRow();
    } else {
      addColumn();
    }
  }

  return (
    <div className={`editable-grid-shell${dragging ? " is-dragging" : ""}`}>
      <div
        className={[
          "data-grid",
          "editable-data-grid",
          `data-grid--${theme}`,
          stickyHeader && headers.length === 1 ? "data-grid--sticky-header" : "",
        ].filter(Boolean).join(" ")}
      >
        <div className="editable-table-stage">
          <button
            className={`editable-grid-edge-add editable-grid-column-edge-add${dragging?.kind === "column" ? " is-delete-target" : ""}`}
            type="button"
            aria-label={dragging?.kind === "column" ? "열 삭제 영역" : "열 추가"}
            title="클릭해 열 추가 · 셀 절반 이상 안쪽으로 끌어 끝 열 삭제"
            onClick={() => clickEdgeAdd("column")}
            onPointerDown={(event) => startEdgeResize(event, "column")}
            onPointerMove={(event) => updateEdgeResize(event, "column")}
            onPointerUp={(event) => finishEdgeResize(event, "column")}
            onPointerCancel={cancelEdgeResize}
            onDragOver={(event) => {
              if (dragging?.kind !== "column") return;
              event.preventDefault();
              event.dataTransfer.dropEffect = "move";
            }}
            onDrop={(event) => {
              if (dragging?.kind !== "column") return;
              event.preventDefault();
              dropToDelete();
            }}
          >
            {dragging?.kind === "column" ? (
              <Trash2 aria-hidden="true" size={13} />
            ) : (
              <Plus aria-hidden="true" size={13} />
            )}
          </button>
          <button
            className={`editable-grid-edge-add editable-grid-row-edge-add${dragging?.kind === "row" ? " is-delete-target" : ""}`}
            type="button"
            aria-label={dragging?.kind === "row" ? "행 삭제 영역" : "행 추가"}
            title="클릭해 행 추가 · 셀 절반 이상 안쪽으로 끌어 끝 행 삭제"
            onClick={() => clickEdgeAdd("row")}
            onPointerDown={(event) => startEdgeResize(event, "row")}
            onPointerMove={(event) => updateEdgeResize(event, "row")}
            onPointerUp={(event) => finishEdgeResize(event, "row")}
            onPointerCancel={cancelEdgeResize}
            onDragOver={(event) => {
              if (dragging?.kind !== "row") return;
              event.preventDefault();
              event.dataTransfer.dropEffect = "move";
            }}
            onDrop={(event) => {
              if (dragging?.kind !== "row") return;
              event.preventDefault();
              dropToDelete();
            }}
          >
            {dragging?.kind === "row" ? (
              <Trash2 aria-hidden="true" size={13} />
            ) : (
              <Plus aria-hidden="true" size={13} />
            )}
          </button>
        <table>
        <colgroup>
          {columns.map((column) => (
            <col key={column.key} style={column.width ? { width: column.width } : undefined} />
          ))}
        </colgroup>
        <thead>
          {headers.map((headerRow, headerLevel) => (
          <tr key={`header-${headerLevel}`}>
            {headerRow.map((header) => {
              if (!header.isLeaf) {
                return (
                  <th
                    key={header.key}
                    colSpan={header.colSpan}
                    rowSpan={header.rowSpan}
                    className="align-center editable-grid-group-header"
                  >
                    <span>{header.label}</span>
                    {header.labelEn ? <small>{header.labelEn}</small> : null}
                  </th>
                );
              }
              const columnIndex = header.columnIndexes[0];
              const column = columns[columnIndex];
              const editorKey = `header-${columnIndex}-${column.key}`;
              return (
                <th
                  key={header.key}
                  colSpan={header.colSpan}
                  rowSpan={header.rowSpan}
                  className={[
                    `align-${column.align}`,
                    edgeTrimPreview?.kind === "column" && columnIndex >= edgeTrimPreview.keepCount
                      ? "is-trim-preview"
                      : "",
                    dragOver?.kind === "column" && dragOver.index === columnIndex
                      ? "is-drag-over"
                      : "",
                  ].filter(Boolean).join(" ")}
                  draggable
                  title="헤더를 잡고 움직여 열 순서 변경 · 삭제 영역에 놓아 제거"
                  onDragStart={(event) => startDrag(event, "column", columnIndex)}
                  onDragEnd={finishDrag}
                  onDragOver={(event) => {
                    if (dragging?.kind !== "column") return;
                    event.preventDefault();
                    setDragOver({ kind: "column", index: columnIndex });
                  }}
                  onDrop={(event) => {
                    event.preventDefault();
                    dropAt("column", columnIndex);
                  }}
                >
                  <button
                    className="editable-grid-trigger"
                    type="button"
                    draggable
                    aria-label={`${column.label} 헤더 수정`}
                    onDragStart={(event) => {
                      event.stopPropagation();
                      startDrag(event, "column", columnIndex);
                    }}
                    onDragEnd={(event) => {
                      event.stopPropagation();
                      finishDrag();
                    }}
                    onClick={(event) => openEditor(editorKey, event.currentTarget)}
                  >
                    <span>
                      {header.label}
                      {column.footnote_marker ? (
                        <sup className="data-grid__footnote">{column.footnote_marker}</sup>
                      ) : null}
                    </span>
                    {header.labelEn ? <small>{header.labelEn}</small> : null}
                  </button>
                  {activeEditor === editorKey ? (
                    <GridEditPopover
                      label="헤더 수정"
                      value={headerLeaf(column)}
                      valueEn={headerLeafEn(column)}
                      parentPath={headerParentPath(column).join(" / ")}
                      parentPathEn={headerParentPathEn(column).join(" / ")}
                      showParentPath
                      footnote={column.footnote_marker ?? ""}
                      anchor={editorAnchor}
                      onApply={(values) => {
                        updateColumnHeader(columnIndex, {
                          label: values.value,
                          labelEn: values.valueEn,
                          parentPath: values.parentPath,
                          parentPathEn: values.parentPathEn,
                          footnote: values.footnote,
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
          ))}
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => {
            const firstColumnKey = columns[0]?.key;
            const summaryKind = summaryRowKind(row, firstColumnKey);
            return (
              <tr
                className={[
                  summaryKind === "total"
                    ? "data-grid__summary-row"
                    : summaryKind === "subtotal"
                      ? "data-grid__subtotal-row"
                      : "",
                  edgeTrimPreview?.kind === "row" && rowIndex >= edgeTrimPreview.keepCount
                    ? "is-trim-preview"
                    : "",
                  dragOver?.kind === "row" && dragOver.index === rowIndex
                    ? "is-drag-over"
                    : "",
                ].filter(Boolean).join(" ")}
                key={`${row._row_index ?? rowIndex}-${rowIndex}`}
                draggable
                title="행의 아무 셀이나 잡고 움직여 순서 변경 · 삭제 영역에 놓아 제거"
                onDragStart={(event) => startDrag(event, "row", rowIndex)}
                onDragEnd={finishDrag}
                onDragOver={(event) => {
                  if (dragging?.kind !== "row") return;
                  event.preventDefault();
                  setDragOver({ kind: "row", index: rowIndex });
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  dropAt("row", rowIndex);
                }}
              >
                {columns.map((column, columnIndex) => {
                  const editorKey = `cell-${rowIndex}-${column.key}`;
                  const value = String(row[column.key] ?? "");
                  const valueEn = String(row[`${column.key}_en`] ?? "");
                  const footnote = String(row[`${column.key}_footnote`] ?? "");
                  return (
                    <td
                      key={column.key}
                      className={[
                        `align-${column.align}`,
                        edgeTrimPreview?.kind === "column" && columnIndex >= edgeTrimPreview.keepCount
                          ? "is-trim-preview"
                          : "",
                      ].filter(Boolean).join(" ")}
                    >
                      <button
                        className="editable-grid-trigger"
                        type="button"
                        draggable
                        aria-label={`${rowIndex + 1}행 ${column.label} 수정`}
                        onDragStart={(event) => {
                          event.stopPropagation();
                          startDrag(event, "row", rowIndex);
                        }}
                        onDragEnd={(event) => {
                          event.stopPropagation();
                          finishDrag();
                        }}
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
      </div>
    </div>
  );
}

function GridEditPopover({
  label,
  code = "",
  value,
  valueEn,
  footnote,
  parentPath = "",
  parentPathEn = "",
  anchor,
  showCode = false,
  showEnglish = true,
  showFootnote = true,
  showParentPath = false,
  onApply,
  onCancel,
}: {
  label: string;
  code?: string;
  value: string;
  valueEn: string;
  footnote: string;
  parentPath?: string;
  parentPathEn?: string;
  anchor: HTMLElement | null;
  showCode?: boolean;
  showEnglish?: boolean;
  showFootnote?: boolean;
  showParentPath?: boolean;
  onApply: (values: {
    code?: string;
    value: string;
    valueEn: string;
    footnote: string;
    parentPath: string;
    parentPathEn: string;
  }) => void;
  onCancel: () => void;
}) {
  const [position, setPosition] = useState({ left: 0, top: 0 });
  const [draftCode, setDraftCode] = useState(code);
  const [draftValue, setDraftValue] = useState(value);
  const [draftValueEn, setDraftValueEn] = useState(valueEn);
  const [draftFootnote, setDraftFootnote] = useState(footnote);
  const [draftParentPath, setDraftParentPath] = useState(parentPath);
  const [draftParentPathEn, setDraftParentPathEn] = useState(parentPathEn);

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
    setDraftParentPath(parentPath);
    setDraftParentPathEn(parentPathEn);
  }, [code, value, valueEn, footnote, parentPath, parentPathEn]);

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
        {showParentPath ? (
          <label>
            <span>상위 헤더</span>
            <input value={draftParentPath} placeholder="예: 방문 발급 / 국내" onChange={(event) => setDraftParentPath(event.target.value)} />
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
        {showParentPath && showEnglish ? (
          <label>
            <span>상위 영문 헤더</span>
            <input value={draftParentPathEn} onChange={(event) => setDraftParentPathEn(event.target.value)} />
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
              parentPath: draftParentPath,
              parentPathEn: draftParentPathEn,
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
    deleted_part_ids: [],
    parts: draftParts.map((part, partIndex) => {
      const baseline = originalParts.find((item) => item.id === part.id) ?? originalParts[partIndex];
      const suffix = original.parts.length > 0
        ? (part.code.match(/\s+표\s*\d+$/)?.[0] ?? ` 표${partIndex + 1}`)
        : "";
      const replaceStructure = tablePartColumnsChanged(baseline, part) || tablePartHeaderPathsChanged(baseline, part);
      const replaceRows = !replaceStructure && tablePartRowsChanged(baseline, part);
      const columns = replaceStructure ? part.columns.map((column, columnIndex) => ({
        source_col_indexes: [columnIndex],
        label: column.label,
        label_en: column.label_en ?? "",
        header_path: headerPath(column),
        header_path_en: headerPathEn(column),
        footnote_marker: column.footnote_marker ?? "",
      })) : part.columns.flatMap((column) => {
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
        if (replaceStructure || replaceRows) {
          return part.columns.map((column, columnIndex) => ({
            row_index: (replaceStructure ? headerDepth(part.columns) : (part.metadata.header_count ?? 0)) + rowIndex,
            col_index: replaceStructure
              ? columnIndex
              : (columnIndex === 0
                  ? sourceColumnIndexes(column).at(-1) ?? columnIndex
                  : sourceColumnIndexes(column)[0] ?? columnIndex),
            value: String(row[column.key] ?? ""),
            value_en: String(row[`${column.key}_en`] ?? ""),
            footnote_marker: String(row[`${column.key}_footnote`] ?? ""),
          }));
        }
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
        header_count: replaceStructure ? headerDepth(part.columns) : (part.metadata.header_count ?? 0),
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
        replace_structure: replaceStructure,
        replace_rows: replaceRows,
      };
    }),
  };
}

function tablePartColumnsChanged(original: StatTablePart, draft: StatTablePart) {
  if (original.columns.length !== draft.columns.length) {
    return true;
  }
  return original.columns.some((column, index) => column.key !== draft.columns[index]?.key);
}

function tablePartRowsChanged(original: StatTablePart, draft: StatTablePart) {
  if (original.rows.length !== draft.rows.length) {
    return true;
  }
  return original.rows.some(
    (row, index) => Number(row._row_index) !== Number(draft.rows[index]?._row_index),
  );
}

function tablePartHeaderPathsChanged(original: StatTablePart, draft: StatTablePart) {
  if (headerDepth(original.columns) <= 1 && headerDepth(draft.columns) <= 1) {
    return false;
  }
  return original.columns.some((column, index) => {
    const next = draft.columns[index] ?? column;
    return JSON.stringify(headerPath(column)) !== JSON.stringify(headerPath(next)) ||
      JSON.stringify(headerPathEn(column)) !== JSON.stringify(headerPathEn(next));
  });
}

function splitHeaderPath(value: string) {
  return value.split("/").map((item) => item.trim()).filter(Boolean);
}

function headerPath(column: ColumnDefinition) {
  return column.header_path?.filter(Boolean) ?? splitHeaderPath(column.label);
}

function headerPathEn(column: ColumnDefinition) {
  return column.header_path_en?.filter(Boolean) ?? splitHeaderPath(column.label_en ?? "");
}

function headerParentPath(column: ColumnDefinition) {
  return headerPath(column).slice(0, -1);
}

function headerParentPathEn(column: ColumnDefinition) {
  return headerPathEn(column).slice(0, -1);
}

function headerLeaf(column: ColumnDefinition) {
  return headerPath(column).at(-1) ?? column.label;
}

function headerLeafEn(column: ColumnDefinition) {
  return headerPathEn(column).at(-1) ?? column.label_en ?? "";
}

function headerDepth(columns: ColumnDefinition[]) {
  return Math.max(1, ...columns.map((column) => headerPath(column).length));
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
