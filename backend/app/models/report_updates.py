from typing import Literal

from pydantic import BaseModel, Field


class ReportTableDifference(BaseModel):
    table_code: str
    change_type: Literal["matching", "modified", "added", "deleted"]
    changed_cell_count: int = 0
    cell_differences: list["ReportCellDifference"] = Field(default_factory=list)


class ReportCellDifference(BaseModel):
    row_index: int
    col_index: int
    left_value: str = ""
    right_value: str = ""


class ReportUpdateSummary(BaseModel):
    batch_id: int
    base_report_id: int
    report_id: int
    update_kind: str
    changed_table_count: int
    unchanged_table_count: int
    added_table_count: int
    deleted_table_count: int
    changed_cell_count: int
    changed_table_ids: list[int] = Field(default_factory=list)


class ReportComparisonSummary(BaseModel):
    id: int
    left_report_id: int
    right_report_id: int
    total_table_count: int
    matching_table_count: int
    changed_table_count: int
    added_table_count: int
    deleted_table_count: int
    changed_cell_count: int
    tables: list[ReportTableDifference] = Field(default_factory=list)
