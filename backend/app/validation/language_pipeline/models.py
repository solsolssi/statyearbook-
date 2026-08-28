from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMReviewResult:
    processed: int
    inserted_issues: int
    inserted_checks: int
    final_issue_count: int
    skipped_reason: str = ""
    cancelled: bool = False


@dataclass(frozen=True)
class LLMTablePreviewResult:
    run_id: int
    table_code: str
    table_title: str
    model: str
    reviewed_contexts: int
    reviewed_items: int
    results: list[dict[str, Any]]


@dataclass(frozen=True)
class LLMUsageEvent:
    run_id: int
    provider: str
    model: str
    request_kind: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    response_status: str = ""


@dataclass(frozen=True)
class SourceReviewItem:
    issue_id: int
    source_rule_id: str
    candidate_kind: str
    candidate_reason: str
    candidate_expected: str
    table_id: int
    table_code: str
    table_title: str
    table_title_en: str
    unit: str
    base_date: str
    location: str
    row_index: int | None
    col_index: int | None
    current_value: str
    cell_text: str
    row_label: str
    column_label: str
    surrounding_rows: list[str]
    requested_review_type: str = ""
    korean_text: str = ""
    english_text: str = ""
    glossary_matches: list[dict[str, object]] | None = None
    source_record_type: str = "issue"
    source_record_id: int | None = None
    prompt_version: str = ""
    review_fingerprint: str = ""
    source_kind: str = "document"

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "id": self.issue_id,
            "candidate_kind": self.candidate_kind,
            "candidate_reason": self.candidate_reason,
            "candidate_expected": self.candidate_expected,
            "table_code": self.table_code,
            "table_title_ko": self.table_title,
            "table_title_en": self.table_title_en,
            "unit": self.unit,
            "base_date": self.base_date,
            "location": self.location,
            "current_value": self.current_value,
            "cell_text": self.cell_text,
            "row_label": self.row_label,
            "column_label": self.column_label,
            "surrounding_rows": self.surrounding_rows,
            "requested_review_type": self.requested_review_type,
            "korean_text": self.korean_text,
            "english_text": self.english_text,
            "translation_glossary": self.glossary_matches or [],
            "prompt_version": self.prompt_version,
        }
