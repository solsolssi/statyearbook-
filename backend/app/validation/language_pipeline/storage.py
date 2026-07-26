from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.db.connection import DB_PATH, connect
from app.db.schema import init_db
from app.validation.language_pipeline.models import LLMUsageEvent


def usage_event_from_response(
    *,
    run_id: int,
    provider: str,
    model: str,
    request_kind: str,
    response: dict[str, Any],
) -> LLMUsageEvent:
    usage = response.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    input_tokens = _token_count(usage, "input_tokens", "prompt_tokens")
    output_tokens = _token_count(usage, "output_tokens", "completion_tokens")
    total_tokens = _token_count(usage, "total_tokens") or input_tokens + output_tokens
    input_rate = _non_negative_float("LLM_INPUT_COST_PER_MILLION")
    output_rate = _non_negative_float("LLM_OUTPUT_COST_PER_MILLION")
    estimated_cost = (
        input_tokens * input_rate + output_tokens * output_rate
    ) / 1_000_000
    return LLMUsageEvent(
        run_id=run_id,
        provider=provider,
        model=model,
        request_kind=request_kind,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost,
        response_status=str(response.get("status") or ""),
    )


class LLMUsageRepository:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def record(self, event: LLMUsageEvent) -> None:
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                connection.execute(
                    """
                    INSERT INTO llm_usage_events (
                        run_id, provider, model, request_kind,
                        input_tokens, output_tokens, total_tokens,
                        estimated_cost_usd, response_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.run_id,
                        event.provider,
                        event.model,
                        event.request_kind,
                        event.input_tokens,
                        event.output_tokens,
                        event.total_tokens,
                        event.estimated_cost_usd,
                        event.response_status,
                    ),
                )


def _token_count(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            continue
    return 0


def _non_negative_float(name: str) -> float:
    try:
        return max(float(os.getenv(name, "0")), 0.0)
    except ValueError:
        return 0.0
