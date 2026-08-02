from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.db.connection import DB_PATH, connect
from app.db.schema import init_db
from app.domain.enums import LanguageReviewStatus
from app.validation.language_pipeline.pipeline import LanguageReviewPipeline
from app.validation.result_repository import refresh_run_issue_count


@dataclass(frozen=True)
class LanguageValidationResult:
    candidate_count: int
    pending_count: int
    reused_count: int
    blue_candidate_count: int
    source_issue_count: int

    @property
    def status(self) -> LanguageReviewStatus:
        return (
            LanguageReviewStatus.COMPLETED
            if self.pending_count == 0
            else LanguageReviewStatus.PENDING
        )


class LanguageValidationWorkflow:
    """Prepare, reuse and optionally execute linguistic review candidates."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path
        self._pipeline = LanguageReviewPipeline(db_path)

    def run(
        self,
        *,
        report_id: int,
        run_id: int,
        source_path: str,
        include_llm: bool,
        table_ids: list[int] | None = None,
        selected_check_types: frozenset[str] | None = None,
    ) -> LanguageValidationResult:
        result = self._pipeline.run(
            report_id=report_id,
            run_id=run_id,
            source_path=source_path,
            include_llm=include_llm,
            table_ids=table_ids,
            selected_check_types=selected_check_types,
        )

        return LanguageValidationResult(
            candidate_count=result.candidate_count,
            pending_count=result.pending_count,
            reused_count=result.reused_count,
            blue_candidate_count=result.blue_candidate_count,
            source_issue_count=result.source_issue_count,
        )


def refresh_stored_issue_count(connection, run_id: int) -> int:
    issue_count = refresh_run_issue_count(connection, run_id=run_id)
    connection.commit()
    return issue_count


def linguistic_review_counts(db_path: Path, run_id: int) -> tuple[int, int]:
    with connect(db_path) as connection:
        init_db(connection)
        row = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status <> 'reviewed' THEN 1 ELSE 0 END) AS pending
            FROM linguistic_review_candidates
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        return int(row["total"] or 0), int(row["pending"] or 0)
