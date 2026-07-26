from __future__ import annotations

from app.validation.models import ValidationTable


def generate_primary_ratio_specs(table: ValidationTable) -> list[dict]:
    from app.validation import profiles

    checks: list[dict] = []
    for generator in (
        profiles.infer_same_row_ratio_rules,
        profiles.infer_following_component_ratio_rules,
        profiles.infer_column_share_ratio_rules,
    ):
        checks.extend(generator(table))
    return checks


def generate_secondary_ratio_specs(table: ValidationTable) -> list[dict]:
    from app.validation import profiles

    checks: list[dict] = []
    for generator in (
        profiles.infer_named_row_ratio_rules,
        profiles.infer_per_unit_ratio_rules,
        profiles.infer_row_based_ratio_rules,
    ):
        checks.extend(generator(table))
    return checks
