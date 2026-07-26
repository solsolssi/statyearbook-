from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.db.connection import DatabaseConnection, DatabaseRow
from app.models.report import ValidationIssue
from app.validation.models import ValidationTable
from app.validation.presentation import validation_issue_from_row
from app.validation.spec_repository import load_rule_specs_by_id


@dataclass(frozen=True)
class PresentedValidationCheck:
    """One persisted check adapted for every output renderer."""

    source: DatabaseRow
    issue: ValidationIssue


def build_validation_presentations(
    connection: DatabaseConnection,
    checks: Iterable[DatabaseRow],
    validation_tables: dict[int, ValidationTable],
) -> dict[int, PresentedValidationCheck]:
    rows = list(checks)
    specs = load_rule_specs_by_id(connection, rows)
    presentations: dict[int, PresentedValidationCheck] = {}
    for row in rows:
        table = validation_tables[int(row["table_id"])]
        issue = validation_issue_from_row(
            row,
            issue_id=f"check-{row['id']}",
            check_type=str(row["check_type"]),
            header_count=table.header_count,
            matrix=table.matrix,
            spec=specs.get(str(row["rule_id"] or "")),
            include_highlights=True,
        )
        presentations[int(row["id"])] = PresentedValidationCheck(source=row, issue=issue)
    return presentations
