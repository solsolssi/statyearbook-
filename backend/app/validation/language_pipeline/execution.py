from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, Protocol

from app.validation.language_pipeline.models import SourceReviewItem


class ReviewClient(Protocol):
    def review(
        self,
        items: list[SourceReviewItem],
        *,
        require_english_replacement: bool = False,
    ) -> list[dict[str, Any]]: ...


DecisionPredicate = Callable[[dict[str, Any], SourceReviewItem], bool]
DecisionRecovery = Callable[
    [dict[str, Any] | None, SourceReviewItem],
    dict[str, Any] | None,
]
ContextKey = Callable[[SourceReviewItem], tuple[object, ...]]


class ReviewBatchExecutor:
    """Execute one LLM batch and repair incomplete context-bound decisions."""

    def __init__(
        self,
        *,
        decision_needs_retry: DecisionPredicate,
        recover_decision: DecisionRecovery,
        context_key: ContextKey,
    ) -> None:
        self._decision_needs_retry = decision_needs_retry
        self._recover_decision = recover_decision
        self._context_key = context_key

    def execute(
        self,
        client: ReviewClient,
        batch: list[SourceReviewItem],
    ) -> list[dict[str, Any]]:
        decisions_by_id = self._request_map(client, batch)
        for _ in range(2):
            retry_items = self._unresolved(batch, decisions_by_id)
            if not retry_items:
                break
            decisions_by_id.update(
                self._request_map(
                    client,
                    retry_items,
                    require_english_replacement=True,
                )
            )

        for context_items in self._group_by_context(
            self._unresolved(batch, decisions_by_id)
        ):
            for _ in range(2):
                retry_items = self._unresolved(context_items, decisions_by_id)
                if not retry_items:
                    break
                decisions_by_id.update(
                    self._request_map(
                        client,
                        retry_items,
                        require_english_replacement=True,
                    )
                )

        for item in self._unresolved(batch, decisions_by_id):
            recovered = self._recover_decision(decisions_by_id.get(item.issue_id), item)
            if recovered is not None:
                decisions_by_id[item.issue_id] = recovered

        unresolved = self._unresolved(batch, decisions_by_id)
        if unresolved:
            codes = ", ".join(f"{item.table_code}:{item.location}" for item in unresolved)
            samples = []
            for item in unresolved[:5]:
                decision = decisions_by_id.get(item.issue_id, {})
                samples.append(
                    f"id={item.issue_id}, requested={item.requested_review_type}, "
                    f"returned={decision.get('issue_type', 'missing')}, "
                    f"status={decision.get('status', 'missing')}, "
                    f"expected={str(decision.get('expected_value', ''))[:60]!r}"
                )
            raise RuntimeError(
                f"LLM review returned incomplete replacement text: {codes}; "
                f"samples: {' | '.join(samples)}"
            )
        return list(decisions_by_id.values())

    def request_with_retries(
        self,
        client: ReviewClient,
        items: list[SourceReviewItem],
        *,
        require_english_replacement: bool = False,
    ) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return client.review(
                    items,
                    require_english_replacement=require_english_replacement,
                )
            except json.JSONDecodeError as exc:
                last_error = exc
            except RuntimeError as exc:
                if "did not contain structured output" not in str(exc):
                    raise
                last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
        raise RuntimeError(
            "LLM review repeatedly returned malformed structured output"
        ) from last_error

    def _request_map(
        self,
        client: ReviewClient,
        items: list[SourceReviewItem],
        *,
        require_english_replacement: bool = False,
    ) -> dict[int, dict[str, Any]]:
        decisions = self.request_with_retries(
            client,
            items,
            require_english_replacement=require_english_replacement,
        )
        result: dict[int, dict[str, Any]] = {}
        for decision in decisions:
            decision_id = _int_or_none(decision.get("id"))
            if decision_id is not None:
                result[decision_id] = decision
        return result

    def _unresolved(
        self,
        items: list[SourceReviewItem],
        decisions: dict[int, dict[str, Any]],
    ) -> list[SourceReviewItem]:
        return [
            item
            for item in items
            if item.issue_id not in decisions
            or self._decision_needs_retry(decisions[item.issue_id], item)
        ]

    def _group_by_context(
        self,
        items: list[SourceReviewItem],
    ) -> list[list[SourceReviewItem]]:
        grouped: dict[tuple[object, ...], list[SourceReviewItem]] = {}
        for item in items:
            grouped.setdefault(self._context_key(item), []).append(item)
        return list(grouped.values())


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
