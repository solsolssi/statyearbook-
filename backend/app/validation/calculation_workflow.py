from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.db.connection import DB_PATH
from app.validation.engine import ValidationEngine
from app.validation.profile_repository import ValidationProfileRepository
from app.validation.profiles import GPTProfileDraftProvider
from app.validation.repository import ValidationRepository
from app.validation.selection import filter_calculation_results


@dataclass(frozen=True)
class CalculationValidationResult:
    report_id: int
    run_id: int
    table_count: int
    issue_count: int


class CalculationValidationWorkflow:
    """Prepare profiles and execute deterministic validation rules.

    This workflow owns no language or LLM behavior. That boundary keeps
    arithmetic validation reproducible and makes it safe to retry without an
    external API.
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._validation_repository = ValidationRepository(db_path)
        self._profile_repository = ValidationProfileRepository(db_path)

    def run(
        self,
        *,
        report_id: int,
        refresh_profiles: bool = False,
        table_ids: list[int] | None = None,
        selected_rule_keys: list[str] | tuple[str, ...] | None = None,
        use_llm_profiles: bool = False,
    ) -> CalculationValidationResult:
        tables = self._validation_repository.load_tables(report_id, table_ids=table_ids)
        profiles = self._profile_repository.ensure_profiles(
            report_id=report_id,
            tables=tables,
            provider=(
                GPTProfileDraftProvider(review_only=True)
                if use_llm_profiles
                else None
            ),
            refresh=refresh_profiles,
            refresh_needs_review=use_llm_profiles,
        )

        engine = ValidationEngine(profiles=profiles)
        outcome = engine.evaluate(tables)
        if selected_rule_keys is not None:
            outcome.issues, outcome.checks = filter_calculation_results(
                issues=outcome.issues,
                checks=outcome.checks,
                rule_keys=selected_rule_keys,
            )
        run_id = self._validation_repository.save_run(
            report_id=report_id,
            rules_version=(
                f"{engine.rules_version}:selected={','.join(selected_rule_keys)}"
                if selected_rule_keys is not None
                else engine.rules_version
            ),
            issues=outcome.issues,
            checks=outcome.checks,
        )
        return CalculationValidationResult(
            report_id=report_id,
            run_id=run_id,
            table_count=len(tables),
            issue_count=len(outcome.issues),
        )
