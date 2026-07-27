from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
import re
from typing import Iterable

from app.domain.parsed import ParsedTable
from app.yearbook_data.excel_series import (
    SeriesColumn,
    SeriesDataset,
    SeriesRow,
    canonical_key,
)


TOTAL_KEYS = {"계", "합계", "총계", "total", "grandtotal"}


class SeriesMaterializationError(ValueError):
    pass


@dataclass(frozen=True)
class MaterializedTable:
    table: ParsedTable
    strategy: str
    source_periods: tuple[str, ...]


def materialize_series_table(
    template: ParsedTable,
    dataset: SeriesDataset,
    *,
    edition_year: int,
    strategy: str = "auto",
) -> MaterializedTable:
    """Apply a canonical series to an approved prior-year table layout.

    Automatic mode intentionally covers only unambiguous, layout-preserving
    changes. A pivot, split/merge, new dimension or removed dimension must use
    an approved explicit recipe instead of silently reshaping the yearbook.
    """

    target_period = str(edition_year - 1)
    selected_strategy = strategy
    if selected_strategy == "auto":
        selected_strategy = infer_strategy(template, dataset)
    if selected_strategy == "period_rows":
        return materialize_period_rows(
            template,
            dataset,
            target_period=target_period,
        )
    if selected_strategy == "current_period_rows":
        return materialize_current_period_rows(
            template,
            dataset,
            target_period=target_period,
        )
    raise SeriesMaterializationError(
        f"{template.code} {template.title}: 자동 변환할 수 없는 구조입니다. "
        "pivot/split/merge 또는 명시적 표 레시피가 필요합니다."
    )


def infer_strategy(template: ParsedTable, dataset: SeriesDataset) -> str:
    data_rows = template.matrix[template.header_count :]
    if not data_rows:
        raise SeriesMaterializationError(f"{template.code}: 템플릿 데이터 행이 없습니다.")
    first_labels = [first_korean_label(row[0]) for row in data_rows if row]
    if first_labels and all(re.fullmatch(r"(?:19|20)\d{2}", label) for label in first_labels):
        if dataset.dimension_columns:
            raise SeriesMaterializationError(
                f"{template.code}: 연도 행 표인데 원장에 추가 차원이 있어 자동 변환할 수 없습니다."
            )
        return "period_rows"
    if dataset.dimension_columns:
        return "current_period_rows"
    raise SeriesMaterializationError(
        f"{template.code}: 행 차원 또는 연도 행을 판별할 수 없습니다."
    )


def materialize_period_rows(
    template: ParsedTable,
    dataset: SeriesDataset,
    *,
    target_period: str,
) -> MaterializedTable:
    if dataset.dimension_columns:
        raise SeriesMaterializationError(
            f"{template.code}: period_rows 레시피는 추가 차원이 없는 원장만 지원합니다."
        )
    data_row_count = len(template.matrix) - template.header_count
    available = sorted(
        (row for row in dataset.rows if row.period <= target_period),
        key=lambda row: row.period,
    )
    selected = available[-data_row_count:]
    if len(selected) != data_row_count or not selected or selected[-1].period != target_period:
        raise SeriesMaterializationError(
            f"{template.code}: {target_period}까지 필요한 {data_row_count}개 연도 행을 "
            f"원장에서 찾지 못했습니다."
        )

    mapping = match_value_columns(template, dataset)
    matrix = [list(row) for row in template.matrix[: template.header_count]]
    exemplar_rows = template.matrix[template.header_count :]
    for offset, source_row in enumerate(selected):
        exemplar = exemplar_rows[min(offset, len(exemplar_rows) - 1)]
        output = list(exemplar)
        output[0] = source_row.period
        apply_values(output, exemplar, source_row, mapping)
        matrix.append(output)
    return MaterializedTable(
        table=updated_table(template, matrix, target_period),
        strategy="period_rows",
        source_periods=tuple(row.period for row in selected),
    )


def materialize_current_period_rows(
    template: ParsedTable,
    dataset: SeriesDataset,
    *,
    target_period: str,
) -> MaterializedTable:
    if not dataset.dimension_columns:
        raise SeriesMaterializationError(
            f"{template.code}: current_period_rows 레시피에는 행 차원이 필요합니다."
        )
    source_rows = [row for row in dataset.rows if row.period == target_period]
    if not source_rows:
        raise SeriesMaterializationError(
            f"{template.code}: 원장에 {target_period} 데이터가 없습니다."
        )
    source_by_key = {
        dimension_identity(row.dimensions): row
        for row in source_rows
    }
    mapping = match_value_columns(template, dataset)
    matrix = [list(row) for row in template.matrix[: template.header_count]]
    used: set[str] = set()
    missing: list[str] = []
    for exemplar in template.matrix[template.header_count :]:
        if not exemplar:
            continue
        label = first_korean_label(exemplar[0])
        key = dimension_identity((label,))
        source_row = source_by_key.get(key)
        if source_row is None:
            missing.append(label)
            continue
        output = list(exemplar)
        apply_values(output, exemplar, source_row, mapping)
        matrix.append(output)
        used.add(key)

    added = [
        " / ".join(row.dimensions)
        for key, row in source_by_key.items()
        if key not in used
    ]
    if missing or added:
        details: list[str] = []
        if missing:
            details.append("삭제·명칭변경 후보: " + ", ".join(missing[:10]))
        if added:
            details.append("신규 행 후보: " + ", ".join(added[:10]))
        raise SeriesMaterializationError(
            f"{template.code}: 행 구성이 이전 연보와 달라 레시피 승인이 필요합니다. "
            + "; ".join(details)
        )
    return MaterializedTable(
        table=updated_table(template, matrix, target_period),
        strategy="current_period_rows",
        source_periods=(target_period,),
    )


def match_value_columns(
    template: ParsedTable,
    dataset: SeriesDataset,
) -> dict[int, int]:
    template_paths = template_column_paths(template)
    dataset_values = list(dataset.value_columns)
    mapping: dict[int, int] = {}
    unmatched: list[str] = []
    used_source_indexes: set[int] = set()
    for template_index, path in enumerate(template_paths):
        if template_index == 0:
            continue
        exact_candidates = [
            source
            for source in dataset_values
            if source.index not in used_source_indexes
            and normalized_path(path) == normalized_path(source.path)
        ]
        candidates = exact_candidates or [
            source
            for source in dataset_values
            if source.index not in used_source_indexes
            and paths_match(path, source.path)
        ]
        if len(candidates) != 1:
            unmatched.append(" > ".join(path))
            continue
        source = candidates[0]
        mapping[template_index] = value_offset(dataset_values, source)
        used_source_indexes.add(source.index)

    if unmatched:
        raise SeriesMaterializationError(
            f"{template.code}: 원장 측정값과 연보 열을 일치시키지 못했습니다: "
            + ", ".join(unmatched[:10])
        )
    return mapping


def template_column_paths(template: ParsedTable) -> list[tuple[str, ...]]:
    width = max((len(row) for row in template.matrix), default=0)
    header_matrix: list[list[str]] = []
    for source_row in template.matrix[: template.header_count]:
        row: list[str] = []
        previous = ""
        for column_index in range(width):
            value = (
                first_korean_label(source_row[column_index])
                if column_index < len(source_row)
                else ""
            )
            if value:
                previous = value
            row.append(value or previous)
        header_matrix.append(row)
    paths: list[tuple[str, ...]] = []
    for column_index in range(width):
        values: list[str] = []
        for row in header_matrix:
            value = row[column_index]
            if value and (not values or canonical_key(value) != canonical_key(values[-1])):
                values.append(value)
        paths.append(tuple(values))
    return paths


def paths_match(template_path: tuple[str, ...], source_path: tuple[str, ...]) -> bool:
    template_keys = normalized_path(template_path)
    source_keys = normalized_path(source_path)
    if template_keys == source_keys:
        return True
    # Some source systems omit a repeated parent header. Leaf matching is safe
    # only when it still identifies exactly one source column; the caller
    # enforces that uniqueness.
    if not template_keys or not source_keys:
        return False
    template_leaf = template_keys[-1]
    source_leaf = source_keys[-1]
    return (
        template_leaf == source_leaf
        or template_leaf in source_leaf
        or source_leaf in template_leaf
    )


def normalized_path(path: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(canonical_key(value) for value in path if value)


def value_offset(columns: list[SeriesColumn], selected: SeriesColumn) -> int:
    return next(index for index, column in enumerate(columns) if column.index == selected.index)


def apply_values(
    output: list[str],
    exemplar: list[str],
    source_row: SeriesRow,
    mapping: dict[int, int],
) -> None:
    for target_column, source_offset in mapping.items():
        source_value = source_row.values[source_offset]
        exemplar_value = exemplar[target_column] if target_column < len(exemplar) else ""
        output[target_column] = format_like_exemplar(source_value, exemplar_value)


def format_like_exemplar(value: str, exemplar: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        numeric = Decimal(text.replace(",", ""))
    except InvalidOperation:
        return text
    if numeric == 0 and str(exemplar).strip() in {"-", "－"}:
        return "-"
    decimals = 0 if numeric == numeric.to_integral_value() else decimal_places(text)
    if decimals == 0:
        integer = int(numeric)
        return f"{integer:,}" if "," in str(exemplar) else str(integer)
    rendered = f"{numeric:.{decimals}f}"
    if "," not in str(exemplar):
        return rendered
    whole, fraction = rendered.split(".", 1)
    return f"{int(whole):,}.{fraction}"


def decimal_places(value: str) -> int:
    normalized = value.replace(",", "")
    if "." not in normalized:
        return 0
    return len(normalized.rsplit(".", 1)[1].rstrip("0"))


def first_korean_label(value: str) -> str:
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    if not lines:
        return ""
    korean_lines = [line for line in lines if re.search(r"[가-힣]", line)]
    return (korean_lines[0] if korean_lines else lines[0]).strip()


def dimension_identity(values: Iterable[str]) -> str:
    normalized = [canonical_key(value) for value in values]
    normalized = [
        "total" if value in {canonical_key(item) for item in TOTAL_KEYS} else value
        for value in normalized
    ]
    return "|".join(normalized)


def updated_table(
    template: ParsedTable,
    matrix: list[list[str]],
    target_period: str,
) -> ParsedTable:
    prior_years = sorted(
        {
            match.group(0)
            for value in (template.base_date, template.raw_context)
            for match in re.finditer(r"(?:19|20)\d{2}", value or "")
        },
        reverse=True,
    )
    base_date = template.base_date
    raw_context = template.raw_context
    if prior_years:
        previous = prior_years[0]
        base_date = base_date.replace(previous, target_period)
        raw_context = raw_context.replace(previous, target_period)
    return replace(
        template,
        matrix=matrix,
        base_date=base_date,
        raw_context=raw_context,
        cells=(),
        footnote_matrix=[],
        parse_warnings=tuple(
            dict.fromkeys(
                [
                    *template.parse_warnings,
                    f"{target_period} 시계열 원장에서 연보 표를 생성했습니다.",
                ]
            )
        ),
    )
