from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.validation.models import ValidationTable


@dataclass(frozen=True)
class TableStructureAnalysis:
    attributes: dict[str, Any]
    templates: tuple[str, ...]


def analyze_structure(table: ValidationTable) -> TableStructureAnalysis:
    # Local import keeps the extraction incremental while the legacy helpers
    # continue to serve existing callers.
    from app.validation.profiles import analyze_table, detect_templates

    return TableStructureAnalysis(
        attributes=analyze_table(table),
        templates=tuple(detect_templates(table)),
    )
