from __future__ import annotations

from typing import Any

from app.validation.models import ValidationTable
from app.validation.profile_generation.cross_table_profile_generator import (
    generate_cross_table_specs,
)
from app.validation.profile_generation.growth_profile_generator import (
    generate_primary_growth_specs,
    generate_secondary_growth_specs,
)
from app.validation.profile_generation.ratio_profile_generator import (
    generate_primary_ratio_specs,
    generate_secondary_ratio_specs,
)
from app.validation.profile_generation.sum_profile_generator import (
    generate_final_sum_specs,
    generate_initial_sum_specs,
)


def compile_profile_checks(
    table: ValidationTable,
    *,
    analysis: dict[str, Any],
    templates: list[str],
) -> list[dict[str, Any]]:
    """Compile generators in the historical order to preserve check output."""

    del analysis
    from app.validation import profiles

    checks: list[dict[str, Any]] = []
    checks.extend(profiles.common_check_specs(table))
    for template in templates:
        generator = profiles.TEMPLATE_PROFILE_GENERATORS.get(template)
        if generator is not None:
            checks.extend(generator(table))

    checks.extend(generate_initial_sum_specs(table))
    checks.extend(generate_primary_ratio_specs(table))
    checks.extend(generate_primary_growth_specs(table))
    checks.extend(generate_secondary_ratio_specs(table))
    checks.extend(generate_secondary_growth_specs(table))
    checks.extend(generate_final_sum_specs(table))
    checks.extend(generate_cross_table_specs(table))
    checks.extend(profiles.outlier_check_specs(table))

    for check in checks:
        if check.get("check_group") == "ratio":
            check.setdefault(
                "aggregate_strategy",
                "recalculate_from_numerator_and_denominator",
            )
    return profiles.dedupe_check_specs(checks)
