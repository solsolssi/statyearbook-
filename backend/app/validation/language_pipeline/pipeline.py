from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.db.connection import DB_PATH, connect
from app.db.schema import init_db
from app.validation.blue_review import synchronize_blue_review_checks
from app.validation.language_pipeline.candidates import LanguageCandidateGenerator
from app.validation.language_pipeline.resolution import ReusableLanguageResolver


@dataclass(frozen=True)
class LanguagePipelineResult:
    candidate_count: int
    pending_count: int
    reused_count: int
    blue_candidate_count: int
    source_issue_count: int


class LanguageReviewPipeline:
    """Run the language workflow through explicit, independently testable stages."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path
        self._candidate_generator = LanguageCandidateGenerator(db_path)
        self._reusable_resolver = ReusableLanguageResolver(db_path)

    def run(
        self,
        *,
        report_id: int,
        run_id: int,
        source_path: str,
        include_llm: bool,
        table_ids: list[int] | None = None,
        selected_check_types: frozenset[str] | None = None,
    ) -> LanguagePipelineResult:
        generated = self._candidate_generator.generate(
            report_id=report_id,
            run_id=run_id,
            source_path=source_path,
            table_ids=table_ids,
            selected_check_types=selected_check_types,
        )
        if selected_check_types is not None:
            self._keep_selected_results(
                run_id=run_id,
                selected_check_types=selected_check_types,
            )
        reused = self._reusable_resolver.resolve(run_id=run_id)

        if include_llm:
            from app.validation.llm_translation_review import (
                append_llm_translation_reviews,
            )

            llm_result = append_llm_translation_reviews(
                self._db_path,
                report_id=report_id,
                run_id=run_id,
                limit=None,
            )
            if llm_result.skipped_reason:
                raise RuntimeError(
                    "LLM 전수 언어 검수가 실행되지 않았습니다: "
                    f"{llm_result.skipped_reason}"
                )

        if (
            selected_check_types is None
            or "파란색 표기 확인" in selected_check_types
        ):
            synchronize_blue_review_checks(self._db_path, run_id=run_id)
        candidate_count, pending_count = self._review_counts(run_id)
        if include_llm and pending_count:
            raise RuntimeError(
                "LLM 전수 언어 검수가 완료되지 않았습니다: "
                f"{pending_count}/{candidate_count}건 대기"
            )

        return LanguagePipelineResult(
            candidate_count=candidate_count,
            pending_count=pending_count,
            reused_count=reused.resolved_candidates,
            blue_candidate_count=generated.blue_candidates,
            source_issue_count=generated.source_issues,
        )

    def _keep_selected_results(
        self,
        *,
        run_id: int,
        selected_check_types: frozenset[str],
    ) -> None:
        language_types = ("오탈자 검수", "번역 검수", "파란색 표기 확인")
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                if selected_check_types:
                    placeholders = ",".join("?" for _ in selected_check_types)
                    params = [run_id, *sorted(selected_check_types)]
                    connection.execute(
                        f"""
                        DELETE FROM linguistic_review_candidates
                        WHERE run_id = ? AND review_type NOT IN ({placeholders})
                        """,
                        params,
                    )
                    language_placeholders = ",".join("?" for _ in language_types)
                    connection.execute(
                        f"""
                        DELETE FROM validation_checks
                        WHERE run_id = ?
                          AND check_type IN ({language_placeholders})
                          AND check_type NOT IN ({placeholders})
                        """,
                        [run_id, *language_types, *sorted(selected_check_types)],
                    )
                else:
                    connection.execute(
                        "DELETE FROM linguistic_review_candidates WHERE run_id = ?",
                        (run_id,),
                    )
                    placeholders = ",".join("?" for _ in language_types)
                    connection.execute(
                        f"""
                        DELETE FROM validation_checks
                        WHERE run_id = ? AND check_type IN ({placeholders})
                        """,
                        (run_id, *language_types),
                    )

    def _review_counts(self, run_id: int) -> tuple[int, int]:
        with connect(self._db_path) as connection:
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
