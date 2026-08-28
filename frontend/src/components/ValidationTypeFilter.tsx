import { SlidersHorizontal } from "lucide-react";

interface ValidationTypeFilterProps {
  types: string[];
  hiddenTypes: ReadonlySet<string>;
  disabledTypes?: ReadonlySet<string>;
  align?: "left" | "right";
  onVisibilityChange: (type: string, visible: boolean) => void;
  onShowAll: () => void;
  onHideAll: () => void;
}

export function ValidationTypeFilter({
  types,
  hiddenTypes,
  disabledTypes = new Set(),
  align = "left",
  onVisibilityChange,
  onShowAll: _onShowAll,
  onHideAll: _onHideAll,
}: ValidationTypeFilterProps) {
  const enabledTypes = types.filter((type) => !disabledTypes.has(type));
  const visibleCount = enabledTypes.filter((type) => !hiddenTypes.has(type)).length;
  const allVisible = enabledTypes.length > 0 && visibleCount === enabledTypes.length;

  function toggleAllVisible() {
    for (const type of enabledTypes) {
      onVisibilityChange(type, !allVisible);
    }
  }

  return (
    <details className={`validation-type-filter validation-type-filter--${align}`}>
      <summary>
        <SlidersHorizontal aria-hidden="true" size={15} />
        <span>확인 항목</span>
        <strong>
          {visibleCount}/{enabledTypes.length}
        </strong>
      </summary>
      <div className="validation-type-filter__menu">
        <div className="validation-type-filter__heading">
          <strong>목록에 포함할 검수 항목</strong>
          <button type="button" onClick={toggleAllVisible} disabled={enabledTypes.length === 0}>
            {allVisible ? "전체 해제" : "전체 선택"}
          </button>
        </div>
        <div className="validation-type-filter__options">
          {types.map((type) => {
            const disabled = disabledTypes.has(type);
            return (
            <label className={disabled ? "is-disabled" : ""} key={type}>
              <input
                checked={!disabled && !hiddenTypes.has(type)}
                disabled={disabled}
                onChange={(event) => onVisibilityChange(type, event.target.checked)}
                type="checkbox"
              />
              <span>{type}</span>
            </label>
            );
          })}
        </div>
      </div>
    </details>
  );
}
