from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.db.connection import DB_PATH, DatabaseConnection, connect
from app.db.schema import init_db


@dataclass(frozen=True)
class ReusableResolutionResult:
    inserted_issues: int
    inserted_checks: int
    resolved_candidates: int


@dataclass(frozen=True)
class ResolutionCounts:
    inserted_issues: int = 0
    inserted_checks: int = 0
    resolved_candidates: int = 0

    def __add__(self, other: ResolutionCounts) -> ResolutionCounts:
        return ResolutionCounts(
            inserted_issues=self.inserted_issues + other.inserted_issues,
            inserted_checks=self.inserted_checks + other.inserted_checks,
            resolved_candidates=self.resolved_candidates + other.resolved_candidates,
        )


class DictionaryResolutionStage:
    """Resolve official region and approved glossary matches."""

    def resolve(
        self,
        connection: DatabaseConnection,
        *,
        run_id: int,
    ) -> ResolutionCounts:
        from app.validation.llm_translation_review import (
            resolve_blue_region_candidates,
            resolve_linguistic_candidates_from_glossary,
        )

        region = resolve_blue_region_candidates(connection, run_id)
        glossary = resolve_linguistic_candidates_from_glossary(connection, run_id)
        return ResolutionCounts(*region) + ResolutionCounts(*glossary)


class CacheResolutionStage:
    """Resolve exact prompt/context fingerprints from prior reviewed decisions."""

    def resolve(
        self,
        connection: DatabaseConnection,
        *,
        run_id: int,
        reviewed_model: str,
    ) -> ResolutionCounts:
        from app.validation.llm_translation_review import (
            reuse_cached_linguistic_reviews,
        )

        return ResolutionCounts(
            *reuse_cached_linguistic_reviews(
                connection,
                run_id,
                reviewed_model=reviewed_model,
            )
        )


class ReusableLanguageResolver:
    """Resolve candidates through official dictionaries and the context cache."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path
        self._dictionary_stage = DictionaryResolutionStage()
        self._cache_stage = CacheResolutionStage()

    def resolve(
        self,
        *,
        run_id: int,
        reviewed_model: str | None = None,
    ) -> ReusableResolutionResult:
        if reviewed_model is None:
            from app.validation.llm_translation_review import llm_review_settings

            reviewed_model = str(llm_review_settings()["model"])
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                counts = self._dictionary_stage.resolve(
                    connection,
                    run_id=run_id,
                )
                counts += self._cache_stage.resolve(
                    connection,
                    run_id=run_id,
                    reviewed_model=reviewed_model,
                )
                from app.validation.llm_translation_review import refresh_issue_count

                refresh_issue_count(connection, run_id)
        return ReusableResolutionResult(
            inserted_issues=counts.inserted_issues,
            inserted_checks=counts.inserted_checks,
            resolved_candidates=counts.resolved_candidates,
        )
