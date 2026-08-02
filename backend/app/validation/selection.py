from __future__ import annotations

from collections.abc import Iterable

from app.validation.catalog import validation_catalog_payload
from app.validation.models import ValidationCheckRecord, ValidationIssueRecord


CHECK_TYPES_BY_RULE_KEY: dict[str, frozenset[str]] = {
    "sum": frozenset({"합계 검수", "평균 검수"}),
    "ratio": frozenset({"비율 검수", "증감률 검수", "증감액 검수"}),
    "spelling": frozenset({"오탈자 검수"}),
    "translation": frozenset({"번역 검수"}),
    "metadata": frozenset({"메타정보 검수"}),
    "outlier": frozenset({"이상치 검수"}),
    "blue": frozenset({"파란색 표기 확인"}),
}

CALCULATION_RULE_KEYS = frozenset({"sum", "ratio", "metadata", "outlier"})
LANGUAGE_RULE_KEYS = frozenset({"spelling", "translation", "blue"})


def all_validation_rule_keys() -> tuple[str, ...]:
    return tuple(str(item["key"]) for item in validation_catalog_payload())


def normalize_validation_rule_keys(values: Iterable[str] | None) -> tuple[str, ...]:
    available = all_validation_rule_keys()
    requested = {str(value).strip() for value in values or () if str(value).strip()}
    if not requested:
        return available
    unknown = requested.difference(available)
    if unknown:
        raise ValueError(f"지원하지 않는 검수 항목입니다: {', '.join(sorted(unknown))}")
    return tuple(key for key in available if key in requested)


def check_types_for_rule_keys(rule_keys: Iterable[str]) -> frozenset[str]:
    return frozenset(
        check_type
        for key in rule_keys
        for check_type in CHECK_TYPES_BY_RULE_KEY.get(key, ())
    )


def filter_calculation_results(
    *,
    issues: Iterable[ValidationIssueRecord],
    checks: Iterable[ValidationCheckRecord],
    rule_keys: Iterable[str],
) -> tuple[list[ValidationIssueRecord], list[ValidationCheckRecord]]:
    allowed = check_types_for_rule_keys(set(rule_keys).intersection(CALCULATION_RULE_KEYS))
    return (
        [issue for issue in issues if issue.issue_type in allowed],
        [check for check in checks if check.check_type in allowed],
    )


def selected_language_check_types(rule_keys: Iterable[str]) -> frozenset[str]:
    return check_types_for_rule_keys(set(rule_keys).intersection(LANGUAGE_RULE_KEYS))

