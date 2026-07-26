from __future__ import annotations

from typing import Any

from app.core.llm_client import parse_responses_json


def validated_review_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract only object-shaped review decisions from a structured response."""

    parsed = parse_responses_json(response)
    raw_items = parsed.get("items", [])
    if not isinstance(raw_items, list):
        raise RuntimeError("LLM structured output field 'items' must be an array")
    return [item for item in raw_items if isinstance(item, dict)]
