from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourceStatisticsSummary(BaseModel):
    total_datasets: int = 0
    datasets_with_values: int = 0
    total_values: int = 0
    earliest_period: str = ""
    latest_period: str = ""
    full_imported_at: str = ""
    incremental_imported_at: str = ""


class SourceStatisticListItem(BaseModel):
    external_id: str
    title: str
    source_kind: str = ""
    directory: str = ""
    department: str = ""
    item_count: int = 0
    value_count: int = 0
    period_count: int = 0
    earliest_period: str = ""
    latest_period: str = ""


class SourceStatisticsOverview(BaseModel):
    summary: SourceStatisticsSummary
    datasets: list[SourceStatisticListItem]


class SourceStatisticPeriod(BaseModel):
    value: str
    label: str
    row_count: int = 0


class SourceStatisticColumn(BaseModel):
    key: str
    label: str
    data_type: str = ""
    item_data_no: int
    align: str = "right"


class SourceStatisticMetadata(BaseModel):
    source_kind: str = ""
    storage_table: str = ""
    directory: str = ""
    subdirectory: str = ""
    input_status: str = ""
    department: str = ""
    officer_name: str = ""
    input_period: str = ""
    data_reference_time: str = ""


class SourceStatisticDetail(BaseModel):
    external_id: str
    title: str
    selected_period: str
    periods: list[SourceStatisticPeriod]
    columns: list[SourceStatisticColumn]
    rows: list[dict[str, str | int]] = Field(default_factory=list)
    metadata: SourceStatisticMetadata
    total_rows: int = 0


class SourceDataImportResult(BaseModel):
    mode: Literal["append_year"]
    base_report_id: int
    target_year: int
    batch_id: int
    datasets: int = 0
    items: int = 0
    values: int = 0
    inserted_values: int = 0
    updated_values: int = 0
    unchanged_values: int = 0
    reused: bool = False
    generated_report_id: int
    reproduction_run_id: int
