from __future__ import annotations

from app.models.report import ValidationCatalogItem, ValidationProfileSummary, ValidationRunResult
from app.validation.catalog import validation_catalog_payload
from app.validation.profile_repository import ValidationProfileRepository
from app.validation.profiles import ValidationProfile
from app.validation.run_validations import run_validations


class ValidationApplicationService:
    """Application boundary for validation execution and profile decisions."""

    def __init__(self, profiles: ValidationProfileRepository | None = None) -> None:
        self._profiles = profiles or ValidationProfileRepository()

    def run(self, report_id: int | None = None) -> ValidationRunResult:
        return ValidationRunResult(**run_validations(report_id=report_id))

    def catalog(self) -> list[ValidationCatalogItem]:
        return [ValidationCatalogItem(**item) for item in validation_catalog_payload()]

    def list_profiles(self) -> list[ValidationProfileSummary]:
        return [profile_to_summary(profile) for profile in self._profiles.list_profiles()]

    def approve_profile(
        self,
        profile_id: int,
        *,
        approved_by: str,
    ) -> ValidationProfileSummary | None:
        profile = self._profiles.approve_profile(profile_id, approved_by=approved_by)
        return profile_to_summary(profile) if profile is not None else None


def profile_to_summary(profile: ValidationProfile) -> ValidationProfileSummary:
    return ValidationProfileSummary(
        id=profile.id,
        table_code=profile.table_code,
        table_title=profile.table_title,
        structure_signature=profile.structure_signature,
        table_type=profile.table_type,
        status=profile.status,
        source=profile.source,
        rules_count=len(profile.check_specs),
        requires_llm_review=bool(profile.rules.get("requires_llm_review")),
        notes=profile.notes,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        approved_at=profile.approved_at,
        approved_by=profile.approved_by,
    )
