from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from app.validation.profile_specs import PROFILE_DOCUMENT_VERSION, PROFILE_SPEC_VERSION


LEGACY_PROFILE_VERSIONS = {
    "",
    "validation-profile-v1",
    "validation-profile-v2",
    "validation-profile-v3",
}


def migrate_profile_document(raw_rules: Any) -> dict[str, Any]:
    """Upgrade persisted JSON without changing the meaning of existing checks."""

    rules = deepcopy(raw_rules) if isinstance(raw_rules, dict) else {}
    version = str(rules.get("version") or "")
    if version == PROFILE_DOCUMENT_VERSION:
        return rules
    if version not in LEGACY_PROFILE_VERSIONS:
        return rules

    for collection_name in ("checks", "table_rules"):
        collection = rules.get(collection_name)
        if not isinstance(collection, list):
            continue
        for spec in collection:
            if isinstance(spec, dict):
                spec.setdefault("spec_version", PROFILE_SPEC_VERSION)
    rules["version"] = PROFILE_DOCUMENT_VERSION
    rules.setdefault("profile_migrations", []).append(
        {
            "from": version or "unversioned",
            "to": PROFILE_DOCUMENT_VERSION,
        }
    )
    return rules


PROFILE_MIGRATIONS: tuple[tuple[str, Callable[[Any], dict[str, Any]]], ...] = (
    (PROFILE_DOCUMENT_VERSION, migrate_profile_document),
)
