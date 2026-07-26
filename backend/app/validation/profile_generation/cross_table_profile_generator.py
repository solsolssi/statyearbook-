from __future__ import annotations

from app.validation.models import ValidationTable


def generate_cross_table_specs(table: ValidationTable) -> list[dict]:
    """Extension point for structural cross-table inference.

    Current cross-table formulas are curated because a single table cannot
    prove the semantic relationship by itself.
    """

    del table
    return []
