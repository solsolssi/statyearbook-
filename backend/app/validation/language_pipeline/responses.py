from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.llm_client import parse_responses_json


def validated_review_items(
    response: dict[str, Any],
    *,
    requested_review_types: Mapping[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Extract flat decisions from flat or compact context-shaped output.

    The database and validation pipeline intentionally retain one decision per
    review type.  The API response can nevertheless return one outer object per
    cell context, with spelling and translation reviews nested below it.  This
    adapter restores the established flat representation immediately after the
    response is parsed.
    """

    parsed = parse_responses_json(response)
    raw_items = parsed.get("items", [])
    if not isinstance(raw_items, list):
        raise RuntimeError("LLM structured output field 'items' must be an array")
    decisions: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        reviews = item.get("reviews")
        if not isinstance(reviews, list):
            # Backward compatibility for saved fixtures and provider responses
            # generated with the previous one-object-per-review schema.
            decisions.append(item)
            continue

        context_token = str(item.get("context_token") or "")
        for review in reviews:
            if not isinstance(review, dict):
                continue
            decision = dict(review)
            decision["context_token"] = context_token
            try:
                issue_id = int(decision.get("id"))
            except (TypeError, ValueError):
                issue_id = None
            if issue_id is not None and requested_review_types is not None:
                issue_type = requested_review_types.get(issue_id)
                if issue_type:
                    decision["issue_type"] = issue_type
            decisions.append(decision)
    return decisions
