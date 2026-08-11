from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.domain.enums import ProfileStatus


CURATED_PROFILE_PATH = Path(__file__).with_name("curated_profiles.json")
CURATED_PROFILE_DIRECTORY = Path(__file__).with_name("curated_profiles")


@dataclass(frozen=True)
class CuratedProfileApplication:
    checks: list[dict[str, Any]]
    table_type: str
    status: ProfileStatus | str
    notes: str


@lru_cache(maxsize=1)
def curated_profiles() -> dict[str, dict[str, Any]]:
    payloads = curated_profile_payloads()
    if not payloads:
        return {}

    profiles: dict[str, dict[str, Any]] = {}
    direct_profiles: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        for group in payload.get("groups", []):
            profile = group.get("profile", {})
            for code in group.get("codes", []):
                profiles[code] = deepcopy(profile)
        direct_profiles.update(
            {
                code: deepcopy(profile)
                for code, profile in payload.get("profiles", {}).items()
            }
        )

    # A table-specific profile is more precise than a shared fallback group.
    profiles.update(direct_profiles)
    return profiles


def curated_profile_payloads() -> list[dict[str, Any]]:
    """Load chapter files first, retaining the former monolith as a fallback."""

    paths = (
        sorted(CURATED_PROFILE_DIRECTORY.glob("*.json"))
        if CURATED_PROFILE_DIRECTORY.exists()
        else []
    )
    if not paths and CURATED_PROFILE_PATH.exists():
        paths = [CURATED_PROFILE_PATH]

    payloads: list[dict[str, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def apply_curated_profile(
    table_code: str,
    *,
    checks: list[dict[str, Any]],
    table_type: str,
    status: ProfileStatus | str,
    notes: str,
) -> CuratedProfileApplication:
    profile = curated_profiles().get(table_code)
    if profile is None:
        return CuratedProfileApplication(checks=checks, table_type=table_type, status=status, notes=notes)

    curated_checks = [deepcopy(check) for check in checks]
    apply_confidence_overrides(curated_checks, profile.get("confidence_overrides", []))
    suppressions = profile.get("suppress_checks", [])
    if suppressions:
        curated_checks = [
            check
            for check in curated_checks
            if not any(check_matches(check, suppression) for suppression in suppressions)
        ]

    decision = profile.get("decision")
    if decision:
        curated_checks.append(
            {
                "id": f"curated.{table_code}.profile_decision",
                "type": "profile_decision",
                "category": "table",
                "check_group": "profile",
                "check_type": "프로파일 큐레이션",
                "label": str(profile.get("label") or decision),
                "decision": decision,
                "execute": False,
                "confidence": float(profile.get("confidence", 1.0)),
            }
        )

    curated_checks.extend(deepcopy(profile.get("checks", [])))
    return CuratedProfileApplication(
        checks=curated_checks,
        table_type=str(profile.get("table_type") or table_type),
        status=str(profile.get("status") or status),
        notes=str(profile.get("notes") or notes),
    )


def curated_profile_revision(table_code: str) -> str | None:
    """Return a stable revision token for one table-specific curated profile.

    Stored validation profiles keep this token so a corrected curated rule is
    applied on the next validation even when the table's layout is unchanged.
    """

    profile = curated_profiles().get(table_code)
    if profile is None:
        return None
    payload = json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def apply_confidence_overrides(
    checks: list[dict[str, Any]],
    overrides: list[dict[str, Any]],
) -> None:
    for override in overrides:
        match = override.get("match", {})
        confidence = override.get("confidence")
        if confidence is None:
            continue
        for check in checks:
            if check_matches(check, match):
                check["confidence"] = float(confidence)
                check["curated"] = True


def check_matches(check: dict[str, Any], match: dict[str, Any]) -> bool:
    return all(check.get(key) == value for key, value in match.items())
