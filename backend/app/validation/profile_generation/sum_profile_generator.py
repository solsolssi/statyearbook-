from __future__ import annotations

from app.validation.models import ValidationTable


def generate_initial_sum_specs(table: ValidationTable) -> list[dict]:
    from app.validation import profiles

    checks: list[dict] = []
    for generator in (
        profiles.infer_gender_total_rules,
        profiles.infer_header_formula_rules,
    ):
        checks.extend(generator(table))
    return checks


def generate_final_sum_specs(table: ValidationTable) -> list[dict]:
    from app.validation import profiles

    checks: list[dict] = []
    for generator in (
        profiles.infer_wrapped_total_cell_rules,
        profiles.infer_total_column_rules,
        profiles.infer_total_row_rules,
    ):
        checks.extend(generator(table))
    return checks
