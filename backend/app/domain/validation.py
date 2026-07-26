from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import (
    HighlightRole,
    HighlightScope,
    ProfileStatus,
    Severity,
    ValidationStatus,
)


@dataclass(frozen=True)
class HighlightTarget:
    row_index: int | None = None
    col_index: int | None = None
    role: HighlightRole | str = HighlightRole.RELATED
    scope: HighlightScope | str = HighlightScope.CELL


@dataclass(frozen=True)
class ValidationSpec:
    rule_id: str
    check_type: str
    check_label: str
    spec_type: str
    config: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    status: ProfileStatus | str = ProfileStatus.ACTIVE
    confidence: float | None = None


@dataclass(frozen=True)
class ValidationResult:
    table_id: int
    rule_id: str
    check_type: str
    check_label: str
    location: str
    current_value: str
    expected_value: str | None
    difference: str | None
    status: ValidationStatus | str
    severity: Severity | str
    detail: str
    row_index: int | None = None
    col_index: int | None = None
    formula: str | None = None
    profile_id: int | None = None
    confidence: float | None = None
    highlights: tuple[HighlightTarget, ...] = ()


@dataclass(frozen=True)
class LanguageCandidate:
    report_id: int
    table_id: int
    review_type: str
    candidate_kind: str
    location: str
    current_value: str
    row_index: int | None = None
    col_index: int | None = None
    source_kind: str = "document"
    context: dict[str, Any] = field(default_factory=dict)
