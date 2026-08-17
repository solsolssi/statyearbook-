from typing import Literal

from pydantic import BaseModel, Field


class StatisticEditAccess(BaseModel):
    table_id: str
    code: str
    title: str
    source_officer: str = ""
    has_password: bool = True
    is_initial_password: bool = True
    updated_at: str = ""


class ReportEditAccess(BaseModel):
    report_id: int
    year: int
    title: str
    statistics: list[StatisticEditAccess] = Field(default_factory=list)


class ReportEditPasswordRequest(BaseModel):
    new_password: str = Field(min_length=4, max_length=128)
    current_password: str | None = Field(default=None, max_length=128)


class ReportEditAuthenticationRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class TableEditSession(BaseModel):
    access_token: str


class EditableMetadata(BaseModel):
    base_date: str = ""
    note: str = ""
    source: str = ""
    source_department: str = ""
    source_officer: str = ""
    source_extension: str = ""
    source_reference: str = ""


class EditableColumnPatch(BaseModel):
    source_col_indexes: list[int] = Field(min_length=1)
    label: str
    label_en: str = ""
    header_path: list[str] = Field(default_factory=list)
    header_path_en: list[str] = Field(default_factory=list)
    footnote_marker: str = ""


class EditableCellPatch(BaseModel):
    row_index: int = Field(ge=0)
    col_index: int = Field(ge=0)
    value: str = ""
    value_en: str = ""
    footnote_marker: str = ""


class EditableHierarchyPatch(BaseModel):
    kind: Literal["domain", "section"]
    original_code: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    title_en: str = Field(default="", max_length=500)


class EditableTablePart(BaseModel):
    id: str
    code: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    title_en: str = Field(default="", max_length=500)
    unit: str = Field(default="", max_length=200)
    header_count: int = Field(default=0, ge=0)
    metadata: EditableMetadata
    columns: list[EditableColumnPatch] = Field(default_factory=list)
    cells: list[EditableCellPatch] = Field(default_factory=list)
    replace_structure: bool = False
    replace_rows: bool = False


class TableContentUpdateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    title_en: str = Field(default="", max_length=500)
    section_title: str = Field(default="", max_length=500)
    section_title_en: str = Field(default="", max_length=500)
    domain: str = Field(default="", max_length=200)
    hierarchy_patches: list[EditableHierarchyPatch] = Field(default_factory=list)
    deleted_part_ids: list[str] = Field(default_factory=list)
    parts: list[EditableTablePart] = Field(min_length=1)


class StatisticCloneRequest(BaseModel):
    code: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
