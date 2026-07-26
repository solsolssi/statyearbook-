from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.validation.models import ValidationTable

if TYPE_CHECKING:
    from app.validation.profiles import ProfileDraft, ValidationProfile


@runtime_checkable
class ProfileProvider(Protocol):
    """Shared boundary for deterministic and LLM-backed profile providers."""

    source: str

    def draft(
        self,
        table: ValidationTable,
        *,
        previous_profile: ValidationProfile | None = None,
    ) -> ProfileDraft:
        ...
