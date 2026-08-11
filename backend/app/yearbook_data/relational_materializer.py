from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import json

from app.db.connection import DB_PATH, DatabaseConnection, DatabaseRow, connect
from app.services.yearbook_reproduction_service import (
YEAR_PATTERN,
    comparable_label,
    comparable_value,
)
from app.yearbook_data.materializer import format_like_exemplar
from app.yearbook_data.source_snapshots import (
    source_items_relation,
    source_values_relation,
)


TOTAL_LABELS = {"계", "합계", "총계", "소계"}
SHORT_YEAR_PATTERN = re.compile(r"[’'](\d{2})(?!\d)")


@dataclass(frozen=True)
class MaterializedCell:
    row_index: int
    col_index: int
    expected_value: str
    generated_value: str

    @property
    def matches(self) -> bool:
        return self.expected_value == self.generated_value


@dataclass(frozen=True)
class RelationalMaterialization:
    status: str
    cells: tuple[MaterializedCell, ...] = ()
    error: str = ""

    @property
    def mismatch_count(self) -> int:
        return sum(not cell.matches for cell in self.cells)


@dataclass(frozen=True)
class SourceValue:
    item_data_no: int
    class_data_no: int
    value: str


@dataclass(frozen=True)
class SourceItem:
    item_data_no: int
    item_name: str
    full_name: str


class RelationalTableMaterializer:
    """Fill an approved annual-table template from the normalized source ledger."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def materialize(
        self,
        *,
        table_id: int,
        dataset_id: int,
        materializer: str,
        target_year: int,
        allow_shape_change: bool = False,
        update_mode: str = "",
    ) -> RelationalMaterialization:
        with connect(self._db_path) as connection:
            return self.materialize_with_connection(
                connection,
                table_id=table_id,
                dataset_id=dataset_id,
                materializer=materializer,
                target_year=target_year,
                allow_shape_change=allow_shape_change,
                update_mode=update_mode,
            )

    def materialize_with_connection(
        self,
        connection: DatabaseConnection,
        *,
        table_id: int,
        dataset_id: int,
        materializer: str,
        target_year: int,
        allow_shape_change: bool = False,
        update_mode: str = "",
    ) -> RelationalMaterialization:
        cells = connection.execute(
            """
            SELECT row_index, col_index, text_value, is_header
            FROM stat_table_cells
            WHERE table_id = ?
            ORDER BY row_index, col_index
            """,
            (table_id,),
        ).fetchall()
        if not cells:
            return RelationalMaterialization(status="unavailable", error="기준 표 셀이 없습니다.")
        width = max(int(cell["col_index"]) for cell in cells) + 1
        height = max(int(cell["row_index"]) for cell in cells) + 1
        matrix = [["" for _ in range(width)] for _ in range(height)]
        header_rows: set[int] = set()
        for cell in cells:
            row_index = int(cell["row_index"])
            col_index = int(cell["col_index"])
            matrix[row_index][col_index] = str(cell["text_value"] or "")
            if bool(cell["is_header"]):
                header_rows.add(row_index)
        data_start = max(header_rows, default=-1) + 1
        if data_start >= height:
            return RelationalMaterialization(
                status="unavailable",
                error="기준 표의 데이터 행을 찾지 못했습니다.",
            )

        generated = [list(row) for row in matrix]
        item_projection = approved_item_projection(
            connection,
            table_id=table_id,
            target_year=target_year,
        )
        if materializer == "copy":
            error = ""
        elif materializer == "empty_values":
            for row_index in range(data_start, len(generated)):
                for col_index in range(1, len(generated[row_index])):
                    generated[row_index][col_index] = ""
            error = ""
        elif materializer == "period_rows":
            error = apply_period_rows(
                connection,
                generated,
                matrix,
                data_start=data_start,
                dataset_id=dataset_id,
                target_year=target_year,
                update_mode=update_mode,
                item_projection=item_projection,
            )
        elif materializer == "current_period_rows":
            error = apply_current_period_rows(
                connection,
                generated,
                matrix,
                data_start=data_start,
                dataset_id=dataset_id,
                target_year=target_year,
                allow_shape_change=allow_shape_change,
                item_projection=item_projection,
            )
        elif materializer == "period_columns":
            error = apply_period_columns(
                connection,
                generated,
                matrix,
                data_start=data_start,
                dataset_id=dataset_id,
                target_year=target_year,
                update_mode=update_mode,
            )
        else:
            return RelationalMaterialization(
                status="unavailable",
                error=f"{materializer} 변환기는 아직 dry-run 대상이 아닙니다.",
            )
        output_height = max(len(matrix), len(generated))
        output_width = max(
            max((len(row) for row in matrix), default=0),
            max((len(row) for row in generated), default=0),
        )
        output = tuple(
            MaterializedCell(
                row_index=row_index,
                col_index=col_index,
                expected_value=matrix_value(matrix, row_index, col_index),
                generated_value=matrix_value(generated, row_index, col_index),
            )
            for row_index in range(output_height)
            for col_index in range(output_width)
        )
        return RelationalMaterialization(
            status=(
                "unavailable"
                if error
                else (
                    "exact"
                    if all(cell.matches for cell in output)
                    else "source_difference"
                )
            ),
            cells=output,
            error=error,
        )


def approved_item_projection(
    connection: DatabaseConnection,
    *,
    table_id: int,
    target_year: int,
) -> dict[int, int]:
    """Return an approved, explicit source-item projection for one table.

    A few source statistics contain several physical yearbook tables or use a
    hierarchy whose leaf labels repeat (for example three different
    ``과정수`` fields).  Name matching alone is intentionally not allowed to
    guess those mappings.  The projection is stored on the reusable recipe,
    scoped by edition year, and uses one-based source item identifiers and
    zero-based rendered column indexes.
    """
    row = connection.execute(
        """
        SELECT recipe.config_json
        FROM stat_tables table_row
        JOIN yearbook_table_recipes recipe
          ON recipe.table_code = table_row.code
         AND recipe.status = 'approved'
         AND recipe.effective_from_year <= ?
         AND (recipe.effective_to_year IS NULL OR recipe.effective_to_year >= ?)
        WHERE table_row.id = ?
        ORDER BY recipe.revision DESC, recipe.id DESC
        LIMIT 1
        """,
        (target_year, target_year, table_id),
    ).fetchone()
    if row is None:
        return {}
    try:
        raw = json.loads(str(row["config_json"] or "{}"))
        projection = raw.get("item_projection") or {}
        return {
            int(column): int(item)
            for column, item in dict(projection).items()
            if str(column).lstrip("-").isdigit()
            and str(item).lstrip("-").isdigit()
        }
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def apply_period_rows(
    connection: DatabaseConnection,
    generated: list[list[str]],
    template: list[list[str]],
    *,
    data_start: int,
    dataset_id: int,
    target_year: int,
    update_mode: str = "",
    item_projection: dict[int, int] | None = None,
) -> str:
    data_rows = list(range(data_start, len(template)))
    summary_rows = [
        row_index
        for row_index in data_rows
        if is_total_label(template[row_index][0])
    ]
    # Text summaries, cumulative totals, and old combined ranges may precede the
    # annual rows. They remain part of the approved layout while the unambiguous
    # single-year rows are refreshed from the ledger.
    period_data_rows = [
        row_index
        for row_index in data_rows
        if len(YEAR_PATTERN.findall(first_line(template[row_index][0]))) == 1
    ]
    years: list[int] = []
    for row_index in period_data_rows:
        match = YEAR_PATTERN.search(first_line(template[row_index][0]))
        if match is None:
            return "연도 행의 첫 번째 열에서 4자리 연도를 일관되게 찾지 못했습니다."
        years.append(int(match.group(1)))
    if (
        years
        and max(years) == target_year - 1
        and years == sorted(years)
    ):
        if update_mode == "append_period" and period_data_rows:
            insert_at = max(period_data_rows) + 1
            exemplar = [
                replace_display_years(value, {years[-1]: target_year})
                for value in template[period_data_rows[-1]]
            ]
            template.insert(insert_at, list(exemplar))
            generated.insert(insert_at, list(exemplar))
            summary_rows = [
                row_index + 1 if row_index >= insert_at else row_index
                for row_index in summary_rows
            ]
            period_data_rows.append(insert_at)
            years.append(target_year)
        elif update_mode == "rolling_window" and period_data_rows:
            # A rolling multi-year table keeps its shape.  Remove the oldest
            # displayed period group, retain the intervening rows verbatim,
            # and append a clone of the former final group for the new year.
            # This is deliberately based on the predecessor template and the
            # incremental ledger only; no completed next-year report is used.
            grouped_rows: dict[int, list[int]] = defaultdict(list)
            for row_index, year in zip(period_data_rows, years, strict=True):
                grouped_rows[year].append(row_index)
            oldest_year = min(grouped_rows)
            final_year = max(grouped_rows)
            oldest_rows = grouped_rows[oldest_year]
            final_rows = grouped_rows[final_year]
            if len(oldest_rows) != len(final_rows):
                return "기간별 행 수가 달라 롤링 기간창을 안전하게 이동할 수 없습니다."
            insert_at = len(template)
            for row_index in reversed(oldest_rows):
                del template[row_index]
                del generated[row_index]
            # Original indexes after the removed group move left by this count.
            offset = sum(1 for row_index in oldest_rows if row_index < final_rows[0])
            for row_index in final_rows:
                exemplar = [
                    replace_display_years(value, {final_year: target_year})
                    for value in template[row_index - offset]
                ]
                template.append(list(exemplar))
                generated.append(list(exemplar))
            data_rows = list(range(data_start, len(template)))
            period_data_rows = [
                row_index
                for row_index in data_rows
                if len(YEAR_PATTERN.findall(first_line(template[row_index][0]))) == 1
            ]
            years = [
                int(YEAR_PATTERN.search(first_line(template[row_index][0])).group(1))
                for row_index in period_data_rows
            ]
            summary_rows = [
                row_index for row_index in data_rows if is_total_label(template[row_index][0])
            ]
        else:
            years = [year + 1 for year in years]
    if (
        len(years) >= 2
        and years[-1] < max(years[:-1])
        and max(years[:-1]) >= 2020
    ):
        target_year = max(years[:-1]) + 1
        years[-1] = target_year
    if (
        years
        and years[-1] != target_year
        and len(years) >= 2
        and years[-2] == target_year - 1
        and years[-1] < years[-2]
    ):
        # A small number of imported HWPX cells lost the leading "2" in the
        # final year (for example 2025 → 2005). The ordered window and target
        # period make the intended year unambiguous.
        years[-1] = target_year
    if not years or max(years) != target_year:
        return f"표시 기간의 마지막 연도가 기준연도 {target_year}와 다릅니다."
    if len(set(years)) != len(years):
        return apply_repeated_period_rows(
            connection,
            generated,
            template,
            data_start=data_start,
            period_data_rows=period_data_rows,
            years=years,
            dataset_id=dataset_id,
            target_year=target_year,
        )

    first_source_rows = source_matrix(connection, dataset_id, years[-1])
    if len(first_source_rows) != 1:
        return (
            f"{years[-1]}년 원장 행이 {len(first_source_rows)}개여서 "
            "연도 행에 바로 배치할 수 없습니다."
        )
    column_mapping = item_projection or match_items_to_columns(
        connection,
        dataset_id=dataset_id,
        template=template,
        header_row_count=data_start,
        target_columns=list(range(1, len(template[0]))),
        source_rows=first_source_rows,
    )
    required_columns = [
        col_index
        for col_index in range(1, len(template[0]))
        if any(
            comparable_value(template[row_index][col_index])
            for row_index in period_data_rows
        )
    ]
    if any(col_index not in column_mapping for col_index in required_columns):
        return "원장 항목명과 연보 측정 열을 모두 연결하지 못했습니다."

    rows_by_year: dict[int, dict[int, SourceValue]] = {}
    for row_index, year in zip(period_data_rows, years, strict=True):
        source_rows = source_matrix(connection, dataset_id, year)
        if not source_rows and year != target_year:
            continue
        if len(source_rows) != 1:
            return f"{year}년 원장 행이 {len(source_rows)}개여서 연도 행에 바로 배치할 수 없습니다."
        source_values = source_rows[0]
        rows_by_year[year] = source_values
        generated[row_index][0] = render_source_value(str(year), template[row_index][0])
        for col_index, item_data_no in column_mapping.items():
            source = source_values.get(item_data_no)
            if source is None:
                continue
            generated[row_index][col_index] = render_source_value(
                source.value,
                template[row_index][col_index],
            )
    if summary_rows:
        error = apply_aggregate_row(
            generated,
            template,
            row_index=summary_rows[0],
            column_mapping=column_mapping,
            source_rows=list(rows_by_year.values()),
        )
        # Percentages and other non-additive totals cannot be derived safely.
        # Keep the approved summary cell in that case; detail years still come
        # from the source ledger.
        if error:
            pass
    return ""


def apply_repeated_period_rows(
    connection: DatabaseConnection,
    generated: list[list[str]],
    template: list[list[str]],
    *,
    data_start: int,
    period_data_rows: list[int],
    years: list[int],
    dataset_id: int,
    target_year: int,
) -> str:
    rows_by_year: dict[int, list[int]] = defaultdict(list)
    for row_index, year in zip(period_data_rows, years, strict=True):
        rows_by_year[year].append(row_index)
    target_rows = rows_by_year[target_year]
    target_source_rows = source_matrix(connection, dataset_id, target_year)
    if not target_source_rows:
        return f"{target_year}년 원장 데이터가 없습니다."

    width = len(template[0])
    # A repeated four-digit year in the first column is the display axis, not a
    # source item. Tables whose first column contains a full event/snapshot date
    # still need that column populated from the source.
    first_column_is_year_axis = all(
        re.fullmatch(r"\s*\d{4}\s*", first_line(template[row_index][0]))
        for row_index in period_data_rows
    )
    has_source_date_item = any(
        any(
            keyword in "".join(source_item_path(item))
            for keyword in ("일자", "기준일", "발생일", "연월일", "날짜", "일시")
        )
        for item in source_items(connection, dataset_id).values()
    )
    if not first_column_is_year_axis and not has_source_date_item:
        return apply_dated_period_rows(
            connection,
            generated,
            template,
            data_start=data_start,
            period_data_rows=period_data_rows,
            dataset_id=dataset_id,
            target_year=target_year,
        )
    target_columns = (
        list(range(1, width))
        if first_column_is_year_axis or not has_source_date_item
        else list(range(width))
    )

    if len(target_source_rows) == len(target_rows):
        column_mapping = match_items_to_columns(
            connection,
            dataset_id=dataset_id,
            template=template,
            header_row_count=data_start,
            target_columns=target_columns,
            source_rows=target_source_rows,
        )
        if len(column_mapping) != len(target_columns):
            return "반복 연도 행의 원장 항목과 연보 열을 모두 연결하지 못했습니다."
        dimension_column = next(
            (
                column
                for column in target_columns
                if column_mapping.get(column) is not None
                and any(
                    comparable_value(row[column])
                    for row in (template[index] for index in target_rows)
                )
                and column in {0, 1}
            ),
            target_columns[0] if target_columns else 0,
        )
        dimension_item = column_mapping.get(dimension_column)
        for year, row_indexes in rows_by_year.items():
            source_rows = source_matrix(connection, dataset_id, year)
            if not source_rows and year != target_year:
                continue
            if len(source_rows) != len(row_indexes):
                return (
                    f"{year}년 원장 행 {len(source_rows)}개와 "
                    f"연보 반복 행 {len(row_indexes)}개가 다릅니다."
                )
            ordered = align_source_rows(
                source_rows,
                template,
                row_indexes=row_indexes,
                dimension_item=dimension_item,
                label_col_index=dimension_column,
            )
            if ordered is None:
                return f"{year}년 반복 행의 구분값과 원장 행을 연결하지 못했습니다."
            for row_index, source_row in zip(row_indexes, ordered, strict=True):
                for col_index, item_data_no in column_mapping.items():
                    source = source_row.get(item_data_no)
                    if source is not None:
                        generated[row_index][col_index] = render_source_value(
                            source.value,
                            template[row_index][col_index],
                        )
        return ""

    if len(target_source_rows) != 1:
        return (
            f"{target_year}년 원장 행 {len(target_source_rows)}개와 "
            f"연보 반복 행 {len(target_rows)}개를 연결할 수 없습니다."
        )

    group_sizes = {len(row_indexes) for row_indexes in rows_by_year.values()}
    if len(group_sizes) != 1:
        return "연도별 반복 행 개수가 달라 개별 레시피가 필요합니다."
    mappings_by_position: list[dict[int, int]] = []
    for position in range(len(target_rows)):
        selected_rows = [
            row_indexes[position]
            for row_indexes in rows_by_year.values()
        ]
        compact_template = [
            list(row)
            for row in template[:data_start]
        ] + [list(template[row_index]) for row_index in selected_rows]
        all_source_rows = [
            source_row
            for year in rows_by_year
            for source_row in source_matrix(connection, dataset_id, year)
        ]
        mapping = match_items_to_columns(
            connection,
            dataset_id=dataset_id,
            template=compact_template,
            header_row_count=data_start,
            target_columns=target_columns,
            source_rows=all_source_rows,
        )
        if len(mapping) != len(target_columns):
            return "반복 연도 행의 세부 유형별 원장 항목을 모두 연결하지 못했습니다."
        mappings_by_position.append(mapping)

    for year, row_indexes in rows_by_year.items():
        source_rows = source_matrix(connection, dataset_id, year)
        if not source_rows and year != target_year:
            continue
        if len(source_rows) != 1:
            return f"{year}년 원장 행이 {len(source_rows)}개여서 반복 행에 배치할 수 없습니다."
        source_row = source_rows[0]
        for position, row_index in enumerate(row_indexes):
            for col_index, item_data_no in mappings_by_position[position].items():
                source = source_row.get(item_data_no)
                if source is not None:
                    generated[row_index][col_index] = render_source_value(
                        source.value,
                        template[row_index][col_index],
                    )
    return ""


def apply_dated_period_rows(
    connection: DatabaseConnection,
    generated: list[list[str]],
    template: list[list[str]],
    *,
    data_start: int,
    period_data_rows: list[int],
    dataset_id: int,
    target_year: int,
) -> str:
    target_source_rows = source_matrix(connection, dataset_id, target_year)
    columns = list(range(1, len(template[0])))
    column_mapping = match_items_to_columns(
        connection,
        dataset_id=dataset_id,
        template=template,
        header_row_count=data_start,
        target_columns=columns,
        source_rows=target_source_rows,
    )
    if len(column_mapping) != len(columns):
        return "날짜형 기간 행의 원장 항목과 연보 열을 모두 연결하지 못했습니다."
    for row_index in period_data_rows:
        label = first_line(template[row_index][0])
        year_match = YEAR_PATTERN.search(label)
        if year_match is None:
            continue
        display_year = int(year_match.group(1))
        source_year = (
            display_year - 1
            if re.search(r"(?:^|\D)0?1[./-]0?1(?:\D|$)", label)
            else display_year
        )
        source_rows = source_matrix(connection, dataset_id, source_year)
        if not source_rows and source_year != target_year:
            continue
        if len(source_rows) != 1:
            return (
                f"{source_year}년 날짜형 원장 행이 {len(source_rows)}개여서 "
                "연보 행에 배치할 수 없습니다."
            )
        source_row = source_rows[0]
        for col_index, item_data_no in column_mapping.items():
            source = source_row.get(item_data_no)
            if source is not None:
                generated[row_index][col_index] = render_source_value(
                    source.value,
                    template[row_index][col_index],
                )
    return ""


def apply_current_period_rows(
    connection: DatabaseConnection,
    generated: list[list[str]],
    template: list[list[str]],
    *,
    data_start: int,
    dataset_id: int,
    target_year: int,
    allow_shape_change: bool = False,
    item_projection: dict[int, int] | None = None,
) -> str:
    source_rows = source_matrix(connection, dataset_id, target_year)
    data_rows = list(range(data_start, len(template)))
    if not source_rows:
        return f"{target_year}년 원장 데이터가 없습니다."
    active_item_numbers = {
        item_data_no
        for source_row in source_rows
        for item_data_no in source_row
    }
    if (
        len(source_rows) > 1
        and len(active_item_numbers) >= 2
        and len(template[0]) % len(active_item_numbers) == 0
        and len(template[0]) // len(active_item_numbers) >= 2
    ):
        wrapped_error = apply_wrapped_current_period_rows(
            connection,
            generated,
            template,
            data_start=data_start,
            dataset_id=dataset_id,
            source_rows=source_rows,
            item_count=len(active_item_numbers),
        )
        if wrapped_error is None:
            return ""
    target_columns = (
        list(range(1, len(template[0])))
        if len(source_rows) == 1
        else list(range(len(template[0])))
    )
    column_mapping = item_projection or match_items_to_columns(
        connection,
        dataset_id=dataset_id,
        template=template,
        header_row_count=data_start,
        target_columns=target_columns,
        source_rows=source_rows,
    )
    required_columns = [
        col_index
        for col_index in target_columns
        if column_contains_measurements(
            template,
            data_start=data_start,
            col_index=col_index,
        )
        and not column_is_structural_axis(
            template,
            data_start=data_start,
            col_index=col_index,
        )
    ]
    if not column_mapping or any(
        col_index not in column_mapping for col_index in required_columns
    ):
        return "원장 항목명과 연보 열을 모두 연결하지 못했습니다."
    dimension_column = mapped_dimension_column(
        template,
        data_start=data_start,
        column_mapping=column_mapping,
    )
    dimension_item = column_mapping.get(dimension_column)
    aggregate_rows = [
        row_index
        for row_index in data_rows
        if is_total_label(template[row_index][0])
    ]
    source_has_total = any(
        is_total_label(
            source_row[dimension_item].value
            if dimension_item is not None and dimension_item in source_row
            else ""
        )
        for source_row in source_rows
    )
    derived_aggregate = False
    if len(source_rows) == len(data_rows) and (
        not aggregate_rows or source_has_total
    ):
        detail_rows = data_rows
    elif (
        len(aggregate_rows) == 1
        and not source_has_total
        and len(source_rows) == len(data_rows) - 1
    ):
        detail_rows = [
            row_index for row_index in data_rows if row_index not in aggregate_rows
        ]
        derived_aggregate = True
    elif not allow_shape_change:
        return (
            f"{target_year}년 원장 행 {len(source_rows)}개와 "
            f"연보 데이터 행 {len(data_rows)}개가 다릅니다."
        )
    else:
        detail_rows = [
            row_index for row_index in data_rows if row_index not in aggregate_rows
        ]
    ordered_rows = align_source_rows(
        source_rows,
        template,
        row_indexes=detail_rows,
        dimension_item=dimension_item,
        label_col_index=dimension_column,
    )
    if ordered_rows is None:
        if not allow_shape_change:
            return "원장의 행 구분값과 연보의 행 순서를 일치시키지 못했습니다."
        return rebuild_current_period_rows(
            generated,
            template,
            data_start=data_start,
            source_rows=source_rows,
            column_mapping=column_mapping,
            dimension_item=dimension_item,
            dimension_column=dimension_column,
            aggregate_rows=aggregate_rows,
        )
    if allow_shape_change and len(source_rows) != len(detail_rows):
        return rebuild_current_period_rows(
            generated,
            template,
            data_start=data_start,
            source_rows=source_rows,
            column_mapping=column_mapping,
            dimension_item=dimension_item,
            dimension_column=dimension_column,
            aggregate_rows=aggregate_rows,
        )
    for row_index, source_row in zip(detail_rows, ordered_rows, strict=True):
        for col_index, item_data_no in column_mapping.items():
            source = source_row.get(item_data_no)
            if source is None:
                return f"{target_year}년 원장에 항목 {item_data_no} 값이 없습니다."
            generated[row_index][col_index] = render_source_value(
                source.value,
                template[row_index][col_index],
            )
    if derived_aggregate:
        error = apply_aggregate_row(
            generated,
            template,
            row_index=aggregate_rows[0],
            column_mapping={
                col_index: item_data_no
                for col_index, item_data_no in column_mapping.items()
                if col_index != 0
            },
            source_rows=ordered_rows,
        )
        if error:
            pass
    return ""


def apply_wrapped_current_period_rows(
    connection: DatabaseConnection,
    generated: list[list[str]],
    template: list[list[str]],
    *,
    data_start: int,
    dataset_id: int,
    source_rows: list[dict[int, SourceValue]],
    item_count: int,
) -> str | None:
    width = len(template[0])
    block_count = width // item_count
    block_mappings: list[dict[int, int]] = []
    for block_index in range(block_count):
        columns = list(
            range(block_index * item_count, (block_index + 1) * item_count)
        )
        mapping = match_items_to_columns(
            connection,
            dataset_id=dataset_id,
            template=template,
            header_row_count=data_start,
            target_columns=columns,
            source_rows=source_rows,
        )
        if len(mapping) != len(columns):
            return "wrapped layout does not match"
        block_mappings.append(mapping)
    # Only claim the wrapped layout when every block uses the same source-item
    # sequence (for example 기관/단체 수 repeated twice across the page).
    sequences = [
        tuple(mapping[column] for column in sorted(mapping))
        for mapping in block_mappings
    ]
    if len(set(sequences)) != 1:
        return "wrapped layout does not match"

    data_row_count = len(template) - data_start
    capacity = data_row_count * block_count
    if len(source_rows) > capacity:
        return (
            f"원장 행 {len(source_rows)}개가 연보의 분할 배치 용량 "
            f"{capacity}개를 초과합니다."
        )
    for row_index in range(data_start, len(generated)):
        for col_index in range(width):
            generated[row_index][col_index] = ""
    for source_index, source_row in enumerate(source_rows):
        block_index = source_index // data_row_count
        row_index = data_start + source_index % data_row_count
        mapping = block_mappings[block_index]
        for col_index, item_data_no in mapping.items():
            source = source_row.get(item_data_no)
            if source is not None:
                generated[row_index][col_index] = render_source_value(
                    source.value,
                    template[row_index][col_index],
                )
    return None


def rebuild_current_period_rows(
    generated: list[list[str]],
    template: list[list[str]],
    *,
    data_start: int,
    source_rows: list[dict[int, SourceValue]],
    column_mapping: dict[int, int],
    dimension_item: int | None,
    dimension_column: int,
    aggregate_rows: list[int],
) -> str:
    template_by_label = {
        comparable_value(template[row_index][dimension_column]): template[row_index]
        for row_index in range(data_start, len(template))
        if comparable_value(template[row_index][dimension_column])
    }
    detail_exemplars = [
        template[row_index]
        for row_index in range(data_start, len(template))
        if row_index not in aggregate_rows
    ]
    default_exemplar = detail_exemplars[0] if detail_exemplars else template[data_start]
    source_has_total = any(
        is_total_label(
            source_row[dimension_item].value
            if dimension_item is not None and dimension_item in source_row
            else ""
        )
        for source_row in source_rows
    )
    rebuilt: list[list[str]] = []
    if aggregate_rows and not source_has_total:
        if len(aggregate_rows) != 1:
            return "합계 행이 여러 개여서 전체 교체 시 개별 집계 규칙이 필요합니다."
        aggregate_exemplar = list(template[aggregate_rows[0]])
        for col_index, item_data_no in column_mapping.items():
            if col_index == 0:
                continue
            values = [
                source.value
                for source_row in source_rows
                if (source := source_row.get(item_data_no)) is not None
            ]
            total = additive_total(values, aggregate_exemplar[col_index])
            if total is None:
                # Ratios, averages, and other non-additive measures cannot be
                # reconstructed from detail rows. Preserve the approved total
                # cell unless the ledger supplies an explicit total row.
                continue
            aggregate_exemplar[col_index] = render_source_value(
                decimal_text(total),
                aggregate_exemplar[col_index],
            )
        rebuilt.append(aggregate_exemplar)

    for source_row in source_rows:
        dimension = source_row.get(dimension_item) if dimension_item is not None else None
        source_label = comparable_value(dimension.value) if dimension is not None else ""
        exemplar = list(template_by_label.get(source_label, default_exemplar))
        for col_index, item_data_no in column_mapping.items():
            source = source_row.get(item_data_no)
            if source is None:
                return f"원장에 항목 {item_data_no} 값이 없습니다."
            exemplar[col_index] = render_source_value(
                source.value,
                exemplar[col_index],
            )
        rebuilt.append(exemplar)

    generated[data_start:] = rebuilt
    return ""


def apply_period_columns(
    connection: DatabaseConnection,
    generated: list[list[str]],
    template: list[list[str]],
    *,
    data_start: int,
    dataset_id: int,
    target_year: int,
    update_mode: str = "",
) -> str:
    year_columns: dict[int, int] = {}
    for col_index in range(len(template[0])):
        years: list[int] = []
        for row_index in range(data_start):
            years.extend(header_years(template[row_index][col_index]))
        if years:
            year_columns[col_index] = years[-1]
    # Carry a year across blank cells created by a merged year header.
    for row_index in range(data_start):
        active_year: int | None = None
        for col_index in range(len(template[0])):
            value = template[row_index][col_index]
            matches = header_years(value)
            if matches:
                active_year = matches[-1]
                year_columns[col_index] = active_year
            elif value.strip():
                active_year = None
            elif active_year is not None:
                year_columns.setdefault(col_index, active_year)
    year_counts = Counter(year_columns.values())
    if year_counts:
        latest_year = max(year_counts)
        ordinary_counts = [
            count
            for year, count in year_counts.items()
            if year != latest_year
        ]
        ordinary_width = min(ordinary_counts, default=year_counts[latest_year])
        if (
            ordinary_width > 0
            and year_counts[latest_year] == ordinary_width * 2
        ):
            duplicate_columns = sorted(
                col_index
                for col_index, year in year_columns.items()
                if year == latest_year
            )
            for col_index in duplicate_columns[-ordinary_width:]:
                year_columns[col_index] = latest_year + 1
            target_year = latest_year + 1
    if len(year_columns) < 2:
        return "연도 열을 두 개 이상 찾지 못했습니다."
    if max(year_columns.values()) != target_year:
        displayed_last_year = max(year_columns.values())
        if displayed_last_year == target_year - 1:
            if update_mode == "append_period":
                latest_columns = sorted(
                    col_index
                    for col_index, year in year_columns.items()
                    if year == displayed_last_year
                )
                if not latest_columns:
                    return "최신 연도 열을 찾지 못했습니다."
                original_width = len(template[0])
                for row_index in range(len(template)):
                    copied = [template[row_index][column] for column in latest_columns]
                    if row_index < data_start:
                        copied = [
                            replace_display_years(
                                value,
                                {displayed_last_year: target_year},
                            )
                            for value in copied
                        ]
                    template[row_index].extend(copied)
                    generated[row_index].extend(copied)
                for offset in range(len(latest_columns)):
                    year_columns[original_width + offset] = target_year
            else:
                original_year_columns = dict(year_columns)
                shift_rolling_period_column_values(
                    generated,
                    template,
                    data_start=data_start,
                    original_year_columns=original_year_columns,
                )
                year_columns = {
                    col_index: year + 1
                    for col_index, year in year_columns.items()
                }
                replacements = {
                    year: year + 1 for year in set(original_year_columns.values())
                }
                for row_index in range(data_start):
                    for col_index in range(len(generated[row_index])):
                        generated[row_index][col_index] = replace_display_years(
                            generated[row_index][col_index],
                            replacements,
                        )
        elif (
            source_matrix(connection, dataset_id, target_year)
            and not source_matrix(connection, dataset_id, displayed_last_year)
        ):
            year_columns = {
                col_index: (
                    target_year if year == displayed_last_year else year
                )
                for col_index, year in year_columns.items()
            }
        else:
            return f"표시 기간의 마지막 연도가 기준연도 {target_year}와 다릅니다."

    # Some imported HWPX tables mark only the first tier of a two-tier header.
    # Treat a leading all-label row as the second header tier when the following
    # row clearly contains measurements.
    while (
        data_start + 1 < len(template)
        and not any(
            is_measurement_value(template[data_start][col_index])
            for col_index in year_columns
        )
        and any(
            is_measurement_value(template[data_start + 1][col_index])
            for col_index in year_columns
        )
    ):
        data_start += 1

    label_columns = [
        col_index
        for col_index in range(len(template[0]))
        if col_index not in year_columns
    ]
    data_rows = list(range(data_start, len(template)))
    target_source_rows = source_matrix(connection, dataset_id, target_year)
    if len(data_rows) == 1 and target_source_rows:
        aggregate_error = apply_single_measure_period_columns(
            connection,
            generated,
            template,
            row_index=data_rows[0],
            year_columns=year_columns,
            dataset_id=dataset_id,
            target_year=target_year,
        )
        if aggregate_error is None:
            return ""
    if len(target_source_rows) > 1:
        return apply_multirow_period_columns(
            connection,
            generated,
            template,
            data_start=data_start,
            data_rows=data_rows,
            label_columns=label_columns,
            year_columns=year_columns,
            dataset_id=dataset_id,
            target_year=target_year,
        )
    source_items = active_source_items_for_years(
        connection,
        dataset_id=dataset_id,
        years=set(year_columns.values()),
    )
    row_mapping = match_items_to_rows(
        connection,
        dataset_id=dataset_id,
        template=template,
        data_rows=data_rows,
        label_columns=label_columns,
        year_columns=year_columns,
        active_item_numbers=source_items,
    )
    target_columns = [
        col_index
        for col_index, year in year_columns.items()
        if year == target_year
    ]
    required_rows = [
        row_index
        for row_index in data_rows
        if any(
            is_measurement_value(template[row_index][col_index])
            for col_index in target_columns
        )
    ]
    if not row_mapping or any(
        row_index not in row_mapping for row_index in required_rows
    ):
        return "원장 항목명과 연보 측정 행을 모두 연결하지 못했습니다."

    for col_index, year in year_columns.items():
        rows = source_matrix(connection, dataset_id, year)
        if not rows and year != target_year:
            continue
        if len(rows) != 1:
            return f"{year}년 원장 행이 {len(rows)}개여서 연도 열에 바로 배치할 수 없습니다."
        source_row = rows[0]
        for row_index, item_data_no in row_mapping.items():
            source = source_row.get(item_data_no)
            if source is None:
                continue
            generated[row_index][col_index] = render_source_value(
                source.value,
                template[row_index][col_index],
            )
    return ""


def shift_rolling_period_column_values(
    generated: list[list[str]],
    template: list[list[str]],
    *,
    data_start: int,
    original_year_columns: dict[int, int],
) -> None:
    """Move retained period values with a rolling column window.

    A source ledger can legitimately start later than the period range printed
    in an annual table.  When, for example, a 2015–2024 table becomes
    2016–2025, the values for 2016–2018 cannot be re-read from the increment.
    They must move with their year labels until a source value is available to
    replace them.  This operates per ordinal column within a year group, so it
    also supports repeated measurement columns beneath each period header.
    """

    columns_by_year: dict[int, list[int]] = defaultdict(list)
    for column, year in original_year_columns.items():
        columns_by_year[year].append(column)
    for columns in columns_by_year.values():
        columns.sort()

    source_column_by_destination: dict[int, int] = {}
    for year, destination_columns in columns_by_year.items():
        source_columns = columns_by_year.get(year + 1, [])
        if not source_columns:
            continue
        for offset, destination_column in enumerate(destination_columns):
            if offset < len(source_columns):
                source_column_by_destination[destination_column] = source_columns[
                    offset
                ]

    for row_index in range(data_start, len(generated)):
        original = list(template[row_index])
        for destination_column, source_column in source_column_by_destination.items():
            if source_column < len(original):
                generated[row_index][destination_column] = original[source_column]


def replace_display_years(value: str, replacements: dict[int, int]) -> str:
    return YEAR_PATTERN.sub(
        lambda match: str(replacements.get(int(match.group(1)), int(match.group(1)))),
        value,
    )


def apply_single_measure_period_columns(
    connection: DatabaseConnection,
    generated: list[list[str]],
    template: list[list[str]],
    *,
    row_index: int,
    year_columns: dict[int, int],
    dataset_id: int,
    target_year: int,
) -> str | None:
    coordinate_counts: Counter[tuple[int, int]] = Counter()
    for col_index, year in year_columns.items():
        target_value = comparable_value(template[row_index][col_index])
        if not target_value:
            continue
        for source_row in source_matrix(connection, dataset_id, year):
            for item_data_no, source in source_row.items():
                if comparable_value(source.value) == target_value:
                    coordinate_counts[(source.class_data_no, item_data_no)] += 1
    if not coordinate_counts:
        return "single measure coordinate not found"
    (class_data_no, item_data_no), _ = coordinate_counts.most_common(1)[0]
    for col_index, year in year_columns.items():
        source_rows = source_matrix(connection, dataset_id, year)
        if not source_rows and year != target_year:
            continue
        source = next(
            (
                value
                for source_row in source_rows
                if (value := source_row.get(item_data_no)) is not None
                and value.class_data_no == class_data_no
            ),
            None,
        )
        if source is None:
            same_item_values = [
                value
                for source_row in source_rows
                if (value := source_row.get(item_data_no)) is not None
            ]
            if len(same_item_values) == 1:
                source = same_item_values[0]
        if source is not None:
            generated[row_index][col_index] = render_source_value(
                source.value,
                template[row_index][col_index],
            )
    return None


def apply_multirow_period_columns(
    connection: DatabaseConnection,
    generated: list[list[str]],
    template: list[list[str]],
    *,
    data_start: int,
    data_rows: list[int],
    label_columns: list[int],
    year_columns: dict[int, int],
    dataset_id: int,
    target_year: int,
) -> str:
    target_source_rows = source_matrix(connection, dataset_id, target_year)
    dimension_mapping = match_items_to_columns(
        connection,
        dataset_id=dataset_id,
        template=template,
        header_row_count=data_start,
        target_columns=label_columns,
        source_rows=target_source_rows,
    )
    dimension_column = mapped_dimension_column(
        template,
        data_start=data_start,
        column_mapping=dimension_mapping,
    )
    dimension_item = dimension_mapping.get(dimension_column)

    columns_by_year: dict[int, list[int]] = defaultdict(list)
    for col_index, year in year_columns.items():
        columns_by_year[year].append(col_index)
    mappings_by_year: dict[int, dict[int, int]] = {}
    for year, columns in columns_by_year.items():
        source_rows = source_matrix(connection, dataset_id, year)
        if not source_rows and year != target_year:
            continue
        if not source_rows:
            return f"{year}년 원장 데이터가 없습니다."
        measurement_rows = [
            {
                item_data_no: value
                for item_data_no, value in source_row.items()
                if item_data_no != dimension_item
            }
            for source_row in source_rows
        ]
        mapping = match_items_to_columns(
            connection,
            dataset_id=dataset_id,
            template=template,
            header_row_count=data_start,
            target_columns=columns,
            source_rows=measurement_rows,
        )
        if len(mapping) != len(columns):
            return "원장 항목명과 연보의 연도별 측정 열을 모두 연결하지 못했습니다."
        mappings_by_year[year] = mapping

    for year, columns in columns_by_year.items():
        source_rows = source_matrix(connection, dataset_id, year)
        if not source_rows and year != target_year:
            continue
        mapping = mappings_by_year[year]
        active_dimension_item = dimension_item
        active_dimension_column = dimension_column
        if active_dimension_item is None:
            active_dimension_column, active_dimension_item = best_row_dimension(
                source_rows,
                template,
                row_indexes=data_rows,
                column_mapping=mapping,
            )
        aligned_pairs = align_source_rows_partially(
            source_rows,
            template,
            row_indexes=data_rows,
            dimension_item=active_dimension_item,
            label_col_index=active_dimension_column,
        )
        if not aligned_pairs:
            return f"{year}년 원장 행과 연보 측정 행을 연결하지 못했습니다."
        for row_index, source_row in aligned_pairs:
            for col_index in columns:
                source = source_row.get(mapping[col_index])
                if source is not None:
                    generated[row_index][col_index] = render_source_value(
                        source.value,
                        template[row_index][col_index],
                    )
    return ""


def best_row_dimension(
    source_rows: list[dict[int, SourceValue]],
    template: list[list[str]],
    *,
    row_indexes: list[int],
    column_mapping: dict[int, int],
) -> tuple[int, int | None]:
    best_score = -1.0
    best_column = min(column_mapping, default=0)
    best_item: int | None = None
    for col_index, item_data_no in column_mapping.items():
        source_values = Counter(
            comparable_value(source.value)
            for row in source_rows
            if (source := row.get(item_data_no)) is not None
            and comparable_value(source.value)
        )
        target_values = Counter(
            comparable_value(template[row_index][col_index])
            for row_index in row_indexes
            if comparable_value(template[row_index][col_index])
        )
        score = counter_overlap(source_values, target_values)
        if score > best_score or (score == best_score and col_index < best_column):
            best_score = score
            best_column = col_index
            best_item = item_data_no
    return best_column, best_item


def align_source_rows_partially(
    source_rows: list[dict[int, SourceValue]],
    template: list[list[str]],
    *,
    row_indexes: list[int],
    dimension_item: int | None,
    label_col_index: int,
) -> list[tuple[int, dict[int, SourceValue]]]:
    if dimension_item is not None:
        source_by_label: dict[str, list[dict[int, SourceValue]]] = defaultdict(list)
        for source_row in source_rows:
            source = source_row.get(dimension_item)
            label = comparable_value(source.value) if source is not None else ""
            if label:
                source_by_label[label].append(source_row)
        aligned: list[tuple[int, dict[int, SourceValue]]] = []
        for row_index in row_indexes:
            label = comparable_value(template[row_index][label_col_index])
            candidates = source_by_label.get(label)
            if candidates:
                aligned.append((row_index, candidates.pop(0)))
        if aligned:
            return aligned
    if source_rows and row_indexes:
        return list(zip(row_indexes, source_rows))
    return []


def source_matrix(
    connection: DatabaseConnection,
    dataset_id: int,
    year: int,
) -> list[dict[int, SourceValue]]:
    period = preferred_dataset_period(connection, dataset_id, year)
    if not period:
        return []
    rows = connection.execute(
        f"""
        SELECT data_cycle, data_division, class_data_no, item_data_no,
               data_value, string_value
        FROM {source_values_relation()}
        WHERE dataset_id = ? AND period = ?
        ORDER BY data_cycle, data_division, class_data_no, item_data_no
        """,
        (dataset_id, period),
    ).fetchall()
    if not rows:
        return []
    by_partition: dict[tuple[str, str], list[DatabaseRow]] = defaultdict(list)
    for row in rows:
        by_partition[(str(row["data_cycle"]), str(row["data_division"]))].append(row)
    preferred_key = ("YY", "OD")
    selected = by_partition.get(preferred_key)
    if selected is None:
        selected = max(by_partition.values(), key=len)
    by_class: dict[int, dict[int, SourceValue]] = defaultdict(dict)
    for row in selected:
        item_data_no = int(row["item_data_no"])
        by_class[int(row["class_data_no"])][item_data_no] = SourceValue(
                item_data_no=item_data_no,
                class_data_no=int(row["class_data_no"]),
                value=str(row["string_value"] or row["data_value"] or ""),
            )
    return [
        values
        for _, values in sorted(by_class.items())
    ]


def preferred_dataset_period(
    connection: DatabaseConnection,
    dataset_id: int,
    year: int,
) -> str:
    preferred = f"{year}00"
    row = connection.execute(
        f"""
        SELECT period
        FROM {source_values_relation()}
        WHERE dataset_id = ? AND period LIKE ?
        GROUP BY period
        ORDER BY CASE WHEN period = ? THEN 0 ELSE 1 END, period DESC
        LIMIT 1
        """,
        (dataset_id, f"{year}%", preferred),
    ).fetchone()
    return str(row["period"]) if row is not None else ""


def align_source_rows(
    source_rows: list[dict[int, SourceValue]],
    template: list[list[str]],
    *,
    row_indexes: list[int],
    dimension_item: int | None,
    label_col_index: int = 0,
) -> list[dict[int, SourceValue]] | None:
    by_label: dict[str, dict[int, SourceValue]] = {}
    duplicate_labels: set[str] = set()
    for row in source_rows:
        dimension = row.get(dimension_item) if dimension_item is not None else None
        label = comparable_value(dimension.value) if dimension is not None else ""
        if not label:
            continue
        if label in by_label:
            duplicate_labels.add(label)
        by_label[label] = row
    if by_label and not duplicate_labels:
        aligned: list[dict[int, SourceValue]] = []
        for row_index in row_indexes:
            label = comparable_value(template[row_index][label_col_index])
            source = by_label.get(label)
            if source is None:
                break
            aligned.append(source)
        if len(aligned) == len(source_rows):
            return aligned
    # Some source tables use a hidden row number instead of an explicit label
    # item. Positional use is permitted only when every row has the same width.
    if len(source_rows) == len(row_indexes) and len(
        {len(row) for row in source_rows}
    ) == 1:
        return source_rows
    return None


def apply_aggregate_row(
    generated: list[list[str]],
    template: list[list[str]],
    *,
    row_index: int,
    column_mapping: dict[int, int],
    source_rows: list[dict[int, SourceValue]],
) -> str:
    for col_index, item_data_no in column_mapping.items():
        values = [
            source.value
            for source_row in source_rows
            if (source := source_row.get(item_data_no)) is not None
        ]
        total = additive_total(values, template[row_index][col_index])
        if total is None:
            return (
                f"합계 행의 {col_index + 1}번째 열은 단순 합산할 수 없어 "
                "개별 집계 규칙이 필요합니다."
            )
        generated[row_index][col_index] = render_source_value(
            decimal_text(total),
            template[row_index][col_index],
        )
    return ""


def additive_total(values: list[str], exemplar: str) -> Decimal | None:
    if not values or "%" in exemplar:
        return None
    total = Decimal(0)
    for value in values:
        text = str(value or "").strip().replace(",", "")
        if text in {"", "-", "–", "—", "_"}:
            continue
        if text.endswith("%"):
            return None
        try:
            total += Decimal(text)
        except InvalidOperation:
            return None
    return total


def column_contains_measurements(
    template: list[list[str]],
    *,
    data_start: int,
    col_index: int,
) -> bool:
    return any(
        is_measurement_value(row[col_index])
        for row in template[data_start:]
        if col_index < len(row)
    )


def column_is_structural_axis(
    template: list[list[str]],
    *,
    data_start: int,
    col_index: int,
) -> bool:
    path = template_column_paths(template, data_start).get(col_index, ())
    return any(
        key in {"연도", "연번", "순위", "번호", "기준연도"}
        for key in path
    )


def mapped_dimension_column(
    template: list[list[str]],
    *,
    data_start: int,
    column_mapping: dict[int, int],
) -> int:
    if not column_mapping:
        return 0
    for col_index in sorted(column_mapping):
        has_text_labels = any(
            bool(first_line(row[col_index]))
            and not is_measurement_value(row[col_index])
            for row in template[data_start:]
            if col_index < len(row)
        )
        if has_text_labels:
            return col_index
    return min(column_mapping)


def is_measurement_value(value: str) -> bool:
    text = first_line(value).strip().replace(",", "").replace(" ", "")
    if not text or text in {"-", "–", "—", "_"}:
        return False
    return bool(re.fullmatch(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)%?", text))


def decimal_text(value: Decimal) -> str:
    if value == value.to_integral():
        return str(int(value))
    return format(value.normalize(), "f")


def match_items_to_columns(
    connection: DatabaseConnection,
    *,
    dataset_id: int,
    template: list[list[str]],
    header_row_count: int,
    target_columns: list[int],
    source_rows: list[dict[int, SourceValue]],
) -> dict[int, int]:
    items = source_items(connection, dataset_id)
    active_numbers = {
        item_data_no
        for row in source_rows
        for item_data_no in row
    }
    header_paths = template_column_paths(template, header_row_count)
    candidates: list[tuple[float, int, int]] = []
    for col_index in target_columns:
        target_path = header_paths[col_index]
        target_values = Counter(
            comparable_value(row[col_index])
            for row in template[header_row_count:]
            if comparable_value(row[col_index])
        )
        for item_data_no in active_numbers:
            item = items.get(item_data_no)
            header_score = path_match_score(
                source_item_path(item),
                target_path,
            )
            source_values = Counter(
                comparable_value(row[item_data_no].value)
                for row in source_rows
                if item_data_no in row and comparable_value(row[item_data_no].value)
            )
            value_score = counter_overlap(source_values, target_values)
            score = header_score + value_score * 35
            if score > 0:
                candidates.append((score, col_index, item_data_no))

    mapping = optimal_candidate_mapping(
        candidates,
        target_nodes=target_columns,
        item_nodes=sorted(active_numbers),
    )
    used_items = set(mapping.values())

    remaining_columns = [col for col in target_columns if col not in mapping]
    remaining_items = sorted(active_numbers - used_items)
    if len(remaining_columns) == len(remaining_items):
        for col_index, item_data_no in zip(
            remaining_columns,
            remaining_items,
            strict=True,
        ):
            mapping[col_index] = item_data_no
    return mapping


def match_items_to_rows(
    connection: DatabaseConnection,
    *,
    dataset_id: int,
    template: list[list[str]],
    data_rows: list[int],
    label_columns: list[int],
    year_columns: dict[int, int],
    active_item_numbers: set[int],
) -> dict[int, int]:
    items = source_items(connection, dataset_id)
    row_paths = template_row_paths(template, data_rows, label_columns)
    source_values = source_item_value_counters(
        connection,
        dataset_id=dataset_id,
        years=set(year_columns.values()),
        item_data_numbers=active_item_numbers,
    )
    candidates: list[tuple[float, int, int]] = []
    for row_index, target_path in row_paths.items():
        target_values = Counter(
            comparable_value(template[row_index][col_index])
            for col_index in year_columns
            if comparable_value(template[row_index][col_index])
        )
        for item_data_no in active_item_numbers:
            header_score = path_match_score(
                source_item_path(items.get(item_data_no)),
                target_path,
            )
            value_score = counter_overlap(
                source_values.get(item_data_no, Counter()),
                target_values,
            )
            score = header_score + value_score * 35
            if score > 0:
                candidates.append((score, row_index, item_data_no))
    mapping = optimal_candidate_mapping(
        candidates,
        target_nodes=data_rows,
        item_nodes=sorted(active_item_numbers),
    )
    used_items = set(mapping.values())
    remaining_rows = [row for row in data_rows if row not in mapping]
    remaining_items = sorted(active_item_numbers - used_items)
    if len(remaining_rows) == len(remaining_items):
        ordered_items = [
            item_data_no
            for item_data_no in items
            if item_data_no in remaining_items
        ]
        for row_index, item_data_no in zip(
            remaining_rows,
            ordered_items,
            strict=True,
        ):
            mapping[row_index] = item_data_no
    return mapping


def optimal_candidate_mapping(
    candidates: list[tuple[float, int, int]],
    *,
    target_nodes: list[int],
    item_nodes: list[int],
) -> dict[int, int]:
    """Return a maximum-score one-to-one mapping for a rectangular candidate set.

    The old descending greedy assignment could consume an item needed by another
    row/column and leave an otherwise matchable table incomplete.  A Hungarian
    assignment is deterministic and considers the complete header/value evidence
    at once. Assignments without any evidence are discarded afterward.
    """

    if not target_nodes or not item_nodes:
        return {}
    score_by_pair = {
        (target, item): max(
            score,
            0.0,
        )
        for score, target, item in candidates
    }
    # The rectangular Hungarian implementation requires rows <= columns.
    # When there are fewer source items, no complete one-to-one mapping is
    # possible; solve the transposed problem and return the useful subset.
    transposed = len(target_nodes) > len(item_nodes)
    left_nodes = item_nodes if transposed else target_nodes
    right_nodes = target_nodes if transposed else item_nodes
    maximum_score = max(score_by_pair.values(), default=0.0)
    missing_cost = maximum_score + 1_000_000.0
    costs: list[list[float]] = []
    for left in left_nodes:
        row: list[float] = []
        for right in right_nodes:
            target, item = (right, left) if transposed else (left, right)
            score = score_by_pair.get((target, item))
            row.append(
                maximum_score - score
                if score is not None and score > 0
                else missing_cost
            )
        costs.append(row)

    # Hungarian algorithm for a minimum-cost rectangular assignment.
    row_count = len(left_nodes)
    column_count = len(right_nodes)
    u = [0.0] * (row_count + 1)
    v = [0.0] * (column_count + 1)
    matched_row = [0] * (column_count + 1)
    previous_column = [0] * (column_count + 1)
    for row_index in range(1, row_count + 1):
        matched_row[0] = row_index
        min_cost = [float("inf")] * (column_count + 1)
        used = [False] * (column_count + 1)
        column = 0
        while True:
            used[column] = True
            active_row = matched_row[column]
            delta = float("inf")
            next_column = 0
            for candidate_column in range(1, column_count + 1):
                if used[candidate_column]:
                    continue
                reduced_cost = (
                    costs[active_row - 1][candidate_column - 1]
                    - u[active_row]
                    - v[candidate_column]
                )
                if reduced_cost < min_cost[candidate_column]:
                    min_cost[candidate_column] = reduced_cost
                    previous_column[candidate_column] = column
                if min_cost[candidate_column] < delta:
                    delta = min_cost[candidate_column]
                    next_column = candidate_column
            for candidate_column in range(column_count + 1):
                if used[candidate_column]:
                    u[matched_row[candidate_column]] += delta
                    v[candidate_column] -= delta
                else:
                    min_cost[candidate_column] -= delta
            column = next_column
            if matched_row[column] == 0:
                break
        while True:
            previous = previous_column[column]
            matched_row[column] = matched_row[previous]
            column = previous
            if column == 0:
                break

    output: dict[int, int] = {}
    for column_index in range(1, column_count + 1):
        row_index = matched_row[column_index]
        if row_index == 0:
            continue
        left = left_nodes[row_index - 1]
        right = right_nodes[column_index - 1]
        target, item = (right, left) if transposed else (left, right)
        if score_by_pair.get((target, item), 0.0) > 0:
            output[target] = item
    return output


def source_item_value_counters(
    connection: DatabaseConnection,
    *,
    dataset_id: int,
    years: set[int],
    item_data_numbers: set[int],
) -> dict[int, Counter[str]]:
    if not years or not item_data_numbers:
        return {}
    period_clauses = " OR ".join("period LIKE ?" for _ in years)
    item_placeholders = ",".join("?" for _ in item_data_numbers)
    rows = connection.execute(
        f"""
        SELECT item_data_no, data_value, string_value
        FROM {source_values_relation()}
        WHERE dataset_id = ?
          AND ({period_clauses})
          AND item_data_no IN ({item_placeholders})
        """,
        [
            dataset_id,
            *(f"{year}%" for year in sorted(years)),
            *sorted(item_data_numbers),
        ],
    ).fetchall()
    output: dict[int, Counter[str]] = defaultdict(Counter)
    for row in rows:
        value = comparable_value(
            str(row["string_value"] or row["data_value"] or "")
        )
        if value:
            output[int(row["item_data_no"])][value] += 1
    return dict(output)


def source_items(
    connection: DatabaseConnection,
    dataset_id: int,
) -> dict[int, SourceItem]:
    rows = connection.execute(
        f"""
        SELECT item_data_no, item_name, full_name
        FROM {source_items_relation()}
        WHERE dataset_id = ?
        ORDER BY display_order, item_data_no
        """,
        (dataset_id,),
    ).fetchall()
    return {
        int(row["item_data_no"]): SourceItem(
            item_data_no=int(row["item_data_no"]),
            item_name=str(row["item_name"] or ""),
            full_name=str(row["full_name"] or ""),
        )
        for row in rows
    }


def active_source_items_for_years(
    connection: DatabaseConnection,
    *,
    dataset_id: int,
    years: set[int],
) -> set[int]:
    if not years:
        return set()
    clauses = " OR ".join("period LIKE ?" for _ in years)
    rows = connection.execute(
        f"""
        SELECT DISTINCT item_data_no
        FROM {source_values_relation()}
        WHERE dataset_id = ? AND ({clauses})
        """,
        [dataset_id, *(f"{year}%" for year in sorted(years))],
    ).fetchall()
    return {int(row["item_data_no"]) for row in rows}


def template_column_paths(
    template: list[list[str]],
    header_row_count: int,
) -> dict[int, tuple[str, ...]]:
    width = len(template[0])
    filled_headers: list[list[str]] = []
    for source_row in template[:header_row_count]:
        filled_row: list[str] = []
        previous = ""
        for col_index in range(width):
            value = source_row[col_index]
            if value.strip():
                previous = value
            filled_row.append(value or previous)
        filled_headers.append(filled_row)
    return {
        col_index: tuple(
            key
            for row in filled_headers
            for key in label_keys(row[col_index])
            if key
        )
        for col_index in range(width)
    }


def template_row_paths(
    template: list[list[str]],
    data_rows: list[int],
    label_columns: list[int],
) -> dict[int, tuple[str, ...]]:
    previous_by_column: dict[int, str] = {}
    output: dict[int, tuple[str, ...]] = {}
    for row_index in data_rows:
        values: list[str] = []
        for col_index in label_columns:
            raw = template[row_index][col_index]
            if raw.strip():
                previous_by_column[col_index] = raw
            value = raw or previous_by_column.get(col_index, "")
            values.extend(label_keys(value))
        output[row_index] = tuple(deduplicate(values))
    return output


def source_item_path(item: SourceItem | None) -> tuple[str, ...]:
    if item is None:
        return ()
    raw_path = item.full_name or item.item_name
    values: list[str] = []
    for part in raw_path.split(">"):
        values.extend(label_keys(part))
    return tuple(deduplicate(values))


def path_match_score(
    source_path: tuple[str, ...],
    target_path: tuple[str, ...],
) -> float:
    if not source_path or not target_path:
        return 0
    source_leaf = source_path[-1]
    target_leaf = target_path[-1]
    if source_path == target_path:
        return 140
    if source_leaf == target_leaf:
        shared = len(set(source_path) & set(target_path))
        return 110 + shared
    if source_leaf in target_path or target_leaf in source_path:
        return 85
    if source_leaf in target_leaf or target_leaf in source_leaf:
        return 65
    shared = len(set(source_path) & set(target_path))
    return 25 + shared if shared else 0


def label_keys(value: str) -> list[str]:
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    korean = [line for line in lines if re.search(r"[가-힣]", line)]
    selected = korean or lines[:1]
    return [
        normalized_label_key(comparable_label(line))
        for line in selected
        if comparable_label(line)
    ]


def normalized_label_key(value: str) -> str:
    if value in TOTAL_LABELS:
        return "합계"
    return value.replace("복구액", "복구비")


def is_total_label(value: str) -> bool:
    normalized = comparable_label(first_line(value))
    return bool(
        re.fullmatch(
            r"(?:합계|계|총계|소계)(?:total|subtotal|grandtotal)?",
            normalized,
        )
    )


def deduplicate(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        if value and (not output or output[-1] != value):
            output.append(value)
    return output


def counter_overlap(source: Counter[str], target: Counter[str]) -> float:
    if not source or not target:
        return 0
    overlap = sum(min(count, target.get(value, 0)) for value, count in source.items())
    return overlap / max(1, sum(source.values()))


def render_source_value(source: str, exemplar: str) -> str:
    if comparable_value(source) == comparable_value(exemplar):
        return exemplar
    return format_like_exemplar(source, exemplar)


def first_line(value: str) -> str:
    return next(
        (line.strip() for line in str(value or "").splitlines() if line.strip()),
        "",
    )


def header_years(value: str) -> list[int]:
    output = [
        int(match.group(1))
        for match in YEAR_PATTERN.finditer(str(value or ""))
    ]
    output.extend(
        2000 + int(match.group(1))
        for match in SHORT_YEAR_PATTERN.finditer(str(value or ""))
    )
    return output


def matrix_value(matrix: list[list[str]], row_index: int, col_index: int) -> str:
    if row_index >= len(matrix) or col_index >= len(matrix[row_index]):
        return ""
    return matrix[row_index][col_index]
