from __future__ import annotations

from pathlib import Path
from typing import Any

from app.db.connection import DB_PATH, connect
from app.db.schema import init_db
from app.models.source_statistics import (
    SourceStatisticColumn,
    SourceStatisticDetail,
    SourceStatisticListItem,
    SourceStatisticMetadata,
    SourceStatisticPeriod,
    SourceStatisticsOverview,
    SourceStatisticsSummary,
)


class SourceStatisticsService:
    """Read-only projections for the canonical source-data workspace."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def overview(self) -> SourceStatisticsOverview:
        with connect(self._db_path) as connection:
            init_db(connection)
            summary_row = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM statistical_datasets) AS total_datasets,
                    (SELECT COUNT(DISTINCT dataset_id) FROM statistical_values)
                        AS datasets_with_values,
                    (SELECT COUNT(*) FROM statistical_values) AS total_values,
                    (SELECT MIN(period) FROM statistical_values) AS earliest_period,
                    (SELECT MAX(period) FROM statistical_values) AS latest_period,
                    (
                        SELECT MAX(imported_at)
                        FROM series_import_batches
                        WHERE import_kind = 'relational_full' AND status = 'imported'
                    ) AS full_imported_at,
                    (
                        SELECT MAX(imported_at)
                        FROM series_import_batches
                        WHERE import_kind = 'relational_incremental' AND status = 'imported'
                    ) AS incremental_imported_at
                """
            ).fetchone()
            rows = connection.execute(
                """
                SELECT
                    dataset.id,
                    dataset.external_id,
                    dataset.title,
                    dataset.source_kind,
                    (SELECT COUNT(*) FROM statistical_dataset_items item
                     WHERE item.dataset_id = dataset.id) AS item_count,
                    (SELECT COUNT(*) FROM statistical_values value
                     WHERE value.dataset_id = dataset.id) AS value_count,
                    (SELECT COUNT(DISTINCT value.period) FROM statistical_values value
                     WHERE value.dataset_id = dataset.id) AS period_count,
                    (SELECT MIN(value.period) FROM statistical_values value
                     WHERE value.dataset_id = dataset.id) AS earliest_period,
                    (SELECT MAX(value.period) FROM statistical_values value
                     WHERE value.dataset_id = dataset.id) AS latest_period,
                    COALESCE((
                        SELECT metadata.directory
                        FROM statistical_period_metadata metadata
                        WHERE metadata.dataset_id = dataset.id
                        ORDER BY metadata.period DESC, metadata.id DESC
                        LIMIT 1
                    ), '') AS directory,
                    COALESCE((
                        SELECT metadata.department
                        FROM statistical_period_metadata metadata
                        WHERE metadata.dataset_id = dataset.id
                        ORDER BY metadata.period DESC, metadata.id DESC
                        LIMIT 1
                    ), '') AS department
                FROM statistical_datasets dataset
                WHERE dataset.status = 'active'
                ORDER BY dataset.title, dataset.external_id
                """
            ).fetchall()
            summary = SourceStatisticsSummary(
                total_datasets=int(summary_row["total_datasets"] or 0) if summary_row else 0,
                datasets_with_values=(
                    int(summary_row["datasets_with_values"] or 0) if summary_row else 0
                ),
                total_values=int(summary_row["total_values"] or 0) if summary_row else 0,
                earliest_period=display_period(
                    str(summary_row["earliest_period"] or "") if summary_row else ""
                ),
                latest_period=display_period(
                    str(summary_row["latest_period"] or "") if summary_row else ""
                ),
                full_imported_at=str(summary_row["full_imported_at"] or "") if summary_row else "",
                incremental_imported_at=(
                    str(summary_row["incremental_imported_at"] or "") if summary_row else ""
                ),
            )
            return SourceStatisticsOverview(
                summary=summary,
                datasets=[
                    SourceStatisticListItem(
                        external_id=str(row["external_id"]),
                        title=str(row["title"]),
                        source_kind=str(row["source_kind"] or ""),
                        directory=str(row["directory"] or ""),
                        department=str(row["department"] or ""),
                        item_count=int(row["item_count"] or 0),
                        value_count=int(row["value_count"] or 0),
                        period_count=int(row["period_count"] or 0),
                        earliest_period=display_period(str(row["earliest_period"] or "")),
                        latest_period=display_period(str(row["latest_period"] or "")),
                    )
                    for row in rows
                ],
            )

    def detail(
        self,
        external_id: str,
        *,
        period: str | None = None,
    ) -> SourceStatisticDetail | None:
        with connect(self._db_path) as connection:
            init_db(connection)
            dataset = connection.execute(
                """
                SELECT *
                FROM statistical_datasets
                WHERE external_id = ? AND status = 'active'
                """,
                (external_id,),
            ).fetchone()
            if dataset is None:
                return None
            dataset_id = int(dataset["id"])
            period_rows = connection.execute(
                """
                SELECT period, COUNT(DISTINCT class_data_no) AS row_count
                FROM statistical_values
                WHERE dataset_id = ?
                GROUP BY period
                ORDER BY period DESC
                """,
                (dataset_id,),
            ).fetchall()
            selected_period = select_period(period, period_rows)
            item_rows = connection.execute(
                """
                SELECT item_data_no, item_name, full_name, data_type
                FROM statistical_dataset_items
                WHERE dataset_id = ?
                ORDER BY item_data_no
                """,
                (dataset_id,),
            ).fetchall()
            value_rows = (
                connection.execute(
                    """
                    SELECT *
                    FROM statistical_values
                    WHERE dataset_id = ? AND period = ?
                    ORDER BY data_cycle, data_division, class_data_no, item_data_no
                    """,
                    (dataset_id, selected_period),
                ).fetchall()
                if selected_period
                else []
            )
            metadata_row = connection.execute(
                """
                SELECT *
                FROM statistical_period_metadata
                WHERE dataset_id = ? AND period = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (dataset_id, selected_period),
            ).fetchone()

            item_by_number = {
                int(row["item_data_no"]): row
                for row in item_rows
            }
            observed_numbers = {int(row["item_data_no"]) for row in value_rows}
            all_numbers = sorted({*item_by_number, *observed_numbers})
            columns = [
                source_column(item_data_no, item_by_number.get(item_data_no))
                for item_data_no in all_numbers
            ]
            grouped: dict[tuple[str, str, int], dict[str, str | int]] = {}
            for row in value_rows:
                group_key = (
                    str(row["data_cycle"]),
                    str(row["data_division"]),
                    int(row["class_data_no"]),
                )
                output = grouped.setdefault(
                    group_key,
                    {
                        "_row_number": int(row["class_data_no"]),
                        "_data_cycle": str(row["data_cycle"]),
                        "_data_division": str(row["data_division"]),
                    },
                )
                item_key = f"item_{int(row['item_data_no'])}"
                output[item_key] = display_value(row)
            rows = list(grouped.values())
            return SourceStatisticDetail(
                external_id=str(dataset["external_id"]),
                title=str(dataset["title"]),
                selected_period=selected_period,
                periods=[
                    SourceStatisticPeriod(
                        value=str(row["period"]),
                        label=display_period(str(row["period"])),
                        row_count=int(row["row_count"] or 0),
                    )
                    for row in period_rows
                ],
                columns=columns,
                rows=rows,
                metadata=metadata_from_rows(dataset, metadata_row),
                total_rows=len(rows),
            )


def source_column(item_data_no: int, row: Any | None) -> SourceStatisticColumn:
    if row is None:
        return SourceStatisticColumn(
            key=f"item_{item_data_no}",
            label=f"자료 {item_data_no}",
            item_data_no=item_data_no,
            align="right",
        )
    full_name = str(row["full_name"] or "").strip()
    item_name = str(row["item_name"] or "").strip()
    data_type = str(row["data_type"] or "")
    return SourceStatisticColumn(
        key=f"item_{item_data_no}",
        label=(full_name or item_name or f"자료 {item_data_no}").replace(">", " / "),
        data_type=data_type,
        item_data_no=item_data_no,
        align="left" if data_type == "문자" else "right",
    )


def metadata_from_rows(dataset: Any, metadata: Any | None) -> SourceStatisticMetadata:
    return SourceStatisticMetadata(
        source_kind=str(dataset["source_kind"] or ""),
        storage_table=str(dataset["storage_table"] or ""),
        directory=str(metadata["directory"] or "") if metadata else "",
        subdirectory=str(metadata["subdirectory"] or "") if metadata else "",
        input_status=str(metadata["input_status"] or "") if metadata else "",
        department=str(metadata["department"] or "") if metadata else "",
        officer_name=str(metadata["officer_name"] or "") if metadata else "",
        input_period=str(metadata["input_period"] or "") if metadata else "",
        data_reference_time=str(metadata["data_reference_time"] or "") if metadata else "",
    )


def select_period(requested: str | None, rows: list[Any]) -> str:
    available = [str(row["period"]) for row in rows]
    if requested and requested in available:
        return requested
    return available[0] if available else ""


def display_period(value: str) -> str:
    if len(value) == 6 and value.endswith("00"):
        return value[:4]
    return value


def display_value(row: Any) -> str:
    value = str(row["data_value"] or "")
    if value:
        return value
    return str(row["string_value"] or "")
