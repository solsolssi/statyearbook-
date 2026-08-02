from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.db.connection import DB_PATH, connect
from app.db.schema import init_db
from app.validation.blue_review import append_blue_text_review_checks
from app.validation.linguistic_review import prepare_linguistic_reviews
from app.validation.result_repository import refresh_run_issue_count
from app.validation.source_review import append_source_format_review_checks


@dataclass(frozen=True)
class CandidateGenerationResult:
    language_candidates: int
    blue_candidates: int
    source_issues: int


class LanguageCandidateGenerator:
    """Generate document, blue-source and source-format review candidates."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def generate(
        self,
        *,
        report_id: int,
        run_id: int,
        source_path: str,
        table_ids: list[int] | None = None,
        selected_check_types: frozenset[str] | None = None,
    ) -> CandidateGenerationResult:
        blue_enabled = (
            selected_check_types is None
            or "파란색 표기 확인" in selected_check_types
        )
        spelling_enabled = (
            selected_check_types is None
            or "오탈자 검수" in selected_check_types
        )
        blue_candidates = (
            append_blue_text_review_checks(
                self._db_path,
                report_id=report_id,
                run_id=run_id,
                source_path=source_path,
                table_ids=table_ids,
            )
            if blue_enabled
            else 0
        )
        source_issues = (
            append_source_format_review_checks(
                self._db_path,
                report_id=report_id,
                run_id=run_id,
                table_ids=table_ids,
            )
            if spelling_enabled
            else 0
        )
        with connect(self._db_path) as connection:
            init_db(connection)
            summary = prepare_linguistic_reviews(
                connection,
                report_id=report_id,
                run_id=run_id,
                table_ids=table_ids,
            )
            refresh_run_issue_count(connection, run_id=run_id)
            connection.commit()
        return CandidateGenerationResult(
            language_candidates=summary.candidates,
            blue_candidates=blue_candidates,
            source_issues=source_issues,
        )
