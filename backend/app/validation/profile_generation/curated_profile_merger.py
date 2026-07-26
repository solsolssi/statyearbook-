from __future__ import annotations

from app.domain.enums import ProfileStatus
from app.validation.curated_profiles import (
    CuratedProfileApplication,
    apply_curated_profile,
)


def merge_curated_profile(
    table_code: str,
    *,
    checks: list[dict],
    table_type: str,
    status: ProfileStatus | str,
    notes: str,
) -> CuratedProfileApplication:
    return apply_curated_profile(
        table_code,
        checks=checks,
        table_type=table_type,
        status=status,
        notes=notes,
    )
