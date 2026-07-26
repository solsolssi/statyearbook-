from __future__ import annotations

import hashlib
import json

from app.validation.blue_review import normalize_review_text
from app.validation.language_pipeline.models import SourceReviewItem
from app.validation.linguistic_policy import (
    SPELLING_CHECK_TYPE,
    TRANSLATION_CHECK_TYPE,
)


def prompt_context_key(item: SourceReviewItem) -> tuple[object, ...]:
    return (
        item.table_id,
        item.location,
        item.row_index,
        item.col_index,
        normalize_review_text(item.current_value),
    )


def review_context_token(item: SourceReviewItem) -> str:
    payload = {
        "table_id": item.table_id,
        "table_code": item.table_code,
        "location": normalize_review_text(item.location),
        "row_index": item.row_index,
        "col_index": item.col_index,
        "current_value": normalize_review_text(item.current_value),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return f"ctx_{hashlib.sha256(encoded).hexdigest()[:24]}"


def compact_prompt_items(items: list[SourceReviewItem]) -> list[dict[str, object]]:
    """Send shared cell context once while retaining one request per review type."""

    grouped: dict[tuple[object, ...], dict[str, object]] = {}
    for item in items:
        key = prompt_context_key(item)
        group = grouped.get(key)
        if group is None:
            group = item.to_prompt_dict()
            for field in (
                "id",
                "candidate_kind",
                "candidate_reason",
                "candidate_expected",
                "requested_review_type",
                "prompt_version",
            ):
                group.pop(field, None)
            group["translation_glossary"] = compact_prompt_glossary(
                item.glossary_matches or []
            )
            group["context_token"] = review_context_token(item)
            for field in ("cell_text", "row_label", "column_label"):
                if normalize_review_text(str(group.get(field) or "")) == normalize_review_text(
                    item.current_value
                ):
                    group.pop(field, None)
            group["review_requests"] = []
            grouped[key] = group

        request_item: dict[str, object] = {
            "id": item.issue_id,
            "requested_review_type": item.requested_review_type,
            "candidate_kind": item.candidate_kind,
        }
        if item.source_kind == "blue" and item.candidate_reason:
            request_item["candidate_reason"] = item.candidate_reason
        if item.candidate_expected:
            request_item["candidate_expected"] = item.candidate_expected
        review_requests = group["review_requests"]
        assert isinstance(review_requests, list)
        review_requests.append(request_item)
    return list(grouped.values())


def compact_prompt_glossary(
    entries: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Keep only source-traceable glossary evidence that can affect a decision."""

    compacted: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for entry in entries:
        status = str(entry.get("status") or "")
        if status not in {"approved", "official_verified", "official_name_only"}:
            continue
        source = normalize_review_text(str(entry.get("source") or ""))
        target = normalize_review_text(str(entry.get("target") or ""))
        key = (source.casefold(), target.casefold(), status)
        if key in seen:
            continue
        seen.add(key)
        compacted.append(
            {
                "source": source,
                "target": target,
                "status": status,
                "subcategory": str(entry.get("subcategory") or ""),
                "source_title": normalize_review_text(
                    str(entry.get("source_title") or "")
                ),
                "source_url": str(entry.get("source_url") or ""),
            }
        )
    return compacted[:8]


def chunked_by_context(
    items: list[SourceReviewItem],
    context_size: int,
) -> list[list[SourceReviewItem]]:
    batches: list[list[SourceReviewItem]] = []
    current: list[SourceReviewItem] = []
    context_count = 0
    previous_key: tuple[object, ...] | None = None
    for item in items:
        key = prompt_context_key(item)
        if key != previous_key:
            if current and context_count >= context_size:
                batches.append(current)
                current = []
                context_count = 0
            context_count += 1
            previous_key = key
        current.append(item)
    if current:
        batches.append(current)
    return batches


def group_linguistic_items_by_context(
    items: list[SourceReviewItem],
) -> list[SourceReviewItem]:
    """Keep all review types for one source value contiguous."""

    grouped: dict[tuple[object, ...], list[SourceReviewItem]] = {}
    for item in items:
        grouped.setdefault(prompt_context_key(item), []).append(item)

    type_order = {
        SPELLING_CHECK_TYPE: 0,
        TRANSLATION_CHECK_TYPE: 1,
    }
    return [
        item
        for context_items in grouped.values()
        for item in sorted(
            context_items,
            key=lambda candidate: (
                type_order.get(candidate.requested_review_type, 99),
                candidate.issue_id,
            ),
        )
    ]


def take_contexts(
    items: list[SourceReviewItem],
    context_limit: int,
) -> list[SourceReviewItem]:
    if context_limit <= 0:
        return []
    selected: list[SourceReviewItem] = []
    seen: set[tuple[object, ...]] = set()
    for item in items:
        key = prompt_context_key(item)
        if key not in seen:
            if len(seen) >= context_limit:
                break
            seen.add(key)
        selected.append(item)
    return selected
