from __future__ import annotations

from app.validation.models import ValidationTable


def generate_primary_growth_specs(table: ValidationTable) -> list[dict]:
    from app.validation import profiles

    checks: list[dict] = []
    for generator in (
        profiles.infer_growth_rate_rules,
        profiles.infer_year_rows_change_rate_rules,
    ):
        checks.extend(generator(table))
    return checks


def generate_secondary_growth_specs(table: ValidationTable) -> list[dict]:
    from app.validation.profiles import infer_row_based_growth_rate_rules

    return infer_row_based_growth_rate_rules(table)
