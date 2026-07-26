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
    ) -> CandidateGenerationResult:
        blue_candidates = append_blue_text_review_checks(
            self._db_path,
            report_id=report_id,
            run_id=run_id,
            source_path=source_path,
        )
        source_issues = append_source_format_review_checks(
            self._db_path,
            report_id=report_id,
            run_id=run_id,
        )
        with connect(self._db_path) as connection:
            init_db(connection)
            summary = prepare_linguistic_reviews(
                connection,
                report_id=report_id,
                run_id=run_id,
            )
            refresh_run_issue_count(connection, run_id=run_id)
            connection.commit()
        return CandidateGenerationResult(
            language_candidates=summary.candidates,
            blue_candidates=blue_candidates,
            source_issues=source_issues,
        )
