from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from app.db.connection import DB_PATH, DatabaseConnection, DatabaseRow, connect
from app.db.schema import init_db
from app.domain.enums import LanguageReviewStatus
from app.validation.calculation_workflow import CalculationValidationWorkflow
from app.validation.language_workflow import LanguageValidationWorkflow
from app.validation.repository import ValidationRepository
from app.validation.result_repository import refresh_run_issue_count, validation_problem_count
from app.validation.selection import (
    all_validation_rule_keys,
    check_types_for_rule_keys,
    normalize_validation_rule_keys,
    selected_language_check_types,
)
from app.services.report_update_service import compare_table_rows, tables_by_code


@dataclass(frozen=True)
class ReusableTableValidation:
    target_table_id: int
    source_table_id: int
    source_report_id: int
    source_run_id: int


class ValidationExecutionService:
    """Run user-selected checks and safely reuse exact table results.

    Reuse is based on equal metadata and equal cell values. A matching year is
    useful for finding candidates, but never sufficient by itself.
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path
        self._repository = ValidationRepository(db_path)

    def run(
        self,
        *,
        report_id: int,
        selected_rule_keys: list[str] | tuple[str, ...] | None = None,
        reuse_existing: bool = True,
        include_llm: bool = False,
    ) -> dict[str, object]:
        rule_keys = normalize_validation_rule_keys(selected_rule_keys)
        report = self._repository.report(report_id)
        if report is None:
            raise ValueError("검수할 연보를 찾을 수 없습니다.")

        if reuse_existing:
            existing = self._matching_current_run(report_id, rule_keys)
            if existing is not None:
                return self._result_payload(
                    report_id=report_id,
                    run_id=int(existing["id"]),
                    selected_rule_keys=rule_keys,
                )

        reusable = (
            self._reusable_tables(report, rule_keys)
            if reuse_existing
            else []
        )
        reusable_table_ids = {item.target_table_id for item in reusable}
        target_tables = self._repository.load_tables(report_id)
        local_table_ids = [
            table.id for table in target_tables if table.id not in reusable_table_ids
        ]

        if local_table_ids:
            calculation = CalculationValidationWorkflow(self._db_path).run(
                report_id=report_id,
                selected_rule_keys=rule_keys,
            )
            run_id = calculation.run_id
            self._remove_results_for_tables(run_id, reusable_table_ids)
        else:
            run_id = self._repository.save_run(
                report_id=report_id,
                rules_version=f"shared:selected={','.join(rule_keys)}",
                issues=[],
                checks=[],
            )

        language_types = selected_language_check_types(rule_keys)
        if language_types and local_table_ids:
            LanguageValidationWorkflow(self._db_path).run(
                report_id=report_id,
                run_id=run_id,
                source_path=str(report["source_file_path"]),
                include_llm=include_llm,
                table_ids=local_table_ids,
                selected_check_types=language_types,
            )

        reused_check_count = self._copy_reusable_results(
            run_id=run_id,
            mappings=reusable,
            selected_rule_keys=rule_keys,
        )
        self._finalize_run(
            run_id=run_id,
            selected_rule_keys=rule_keys,
            mappings=reusable,
            reused_check_count=reused_check_count,
        )
        return self._result_payload(
            report_id=report_id,
            run_id=run_id,
            selected_rule_keys=rule_keys,
        )

    def _matching_current_run(
        self,
        report_id: int,
        selected_rule_keys: tuple[str, ...],
    ) -> DatabaseRow | None:
        with connect(self._db_path) as connection:
            init_db(connection)
            rows = connection.execute(
                """
                SELECT *
                FROM validation_runs
                WHERE report_id = ?
                ORDER BY completed_at DESC, id DESC
                """,
                (report_id,),
            ).fetchall()
            for row in rows:
                if run_rule_keys(row) == selected_rule_keys:
                    return row
        return None

    def _reusable_tables(
        self,
        report: DatabaseRow,
        selected_rule_keys: tuple[str, ...],
    ) -> list[ReusableTableValidation]:
        report_id = int(report["id"])
        year = int(report["year"])
        with connect(self._db_path) as connection:
            init_db(connection)
            candidate_ids: list[int] = [report_id]
            if report["base_report_id"] is not None:
                candidate_ids.append(int(report["base_report_id"]))
            candidate_ids.extend(
                int(row["id"])
                for row in connection.execute(
                    """
                    SELECT id
                    FROM annual_reports
                    WHERE year = ? AND id <> ?
                    ORDER BY imported_at DESC, id DESC
                    """,
                    (year, report_id),
                ).fetchall()
            )
            candidate_ids = list(dict.fromkeys(candidate_ids))
            target_tables = tables_by_code(connection, report_id)
            resolved: dict[int, ReusableTableValidation] = {}
            for candidate_report_id in candidate_ids:
                run = latest_compatible_run(
                    connection,
                    candidate_report_id,
                    selected_rule_keys,
                )
                if run is None:
                    continue
                candidate_tables = tables_by_code(connection, candidate_report_id)
                for code, target in target_tables.items():
                    target_id = int(target["id"])
                    if target_id in resolved:
                        continue
                    source = candidate_tables.get(code)
                    if source is None:
                        continue
                    change_type, _, _ = compare_table_rows(connection, target, source)
                    if change_type != "matching":
                        continue
                    resolved[target_id] = ReusableTableValidation(
                        target_table_id=target_id,
                        source_table_id=int(source["id"]),
                        source_report_id=candidate_report_id,
                        source_run_id=int(run["id"]),
                    )
            return list(resolved.values())

    def _remove_results_for_tables(self, run_id: int, table_ids: set[int]) -> None:
        if not table_ids:
            return
        placeholders = ",".join("?" for _ in table_ids)
        params = [run_id, *sorted(table_ids)]
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                connection.execute(
                    f"""
                    DELETE FROM validation_checks
                    WHERE run_id = ? AND table_id IN ({placeholders})
                    """,
                    params,
                )
                connection.execute(
                    f"""
                    DELETE FROM linguistic_review_candidates
                    WHERE run_id = ? AND table_id IN ({placeholders})
                    """,
                    params,
                )

    def _copy_reusable_results(
        self,
        *,
        run_id: int,
        mappings: list[ReusableTableValidation],
        selected_rule_keys: tuple[str, ...],
    ) -> int:
        if not mappings:
            return 0
        check_types = sorted(check_types_for_rule_keys(selected_rule_keys))
        if not check_types:
            return 0
        type_placeholders = ",".join("?" for _ in check_types)
        copied = 0
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                for mapping in mappings:
                    cursor = connection.execute(
                        f"""
                        INSERT INTO validation_checks (
                            run_id, table_id, profile_id, rule_id, check_type,
                            check_label, location, row_index, col_index,
                            current_value, expected_value, difference, status,
                            severity, detail, formula, confidence
                        )
                        SELECT ?, ?, profile_id, rule_id, check_type,
                               check_label, location, row_index, col_index,
                               current_value, expected_value, difference, status,
                               severity, detail, formula, confidence
                        FROM validation_checks
                        WHERE run_id = ? AND table_id = ?
                          AND check_type IN ({type_placeholders})
                        """,
                        (
                            run_id,
                            mapping.target_table_id,
                            mapping.source_run_id,
                            mapping.source_table_id,
                            *check_types,
                        ),
                    )
                    copied += max(int(cursor.rowcount or 0), 0)
                    connection.execute(
                        f"""
                        INSERT INTO linguistic_review_candidates (
                            run_id, table_id, review_type, candidate_kind, source_kind,
                            location, row_index, col_index, current_value, korean_text,
                            english_text, glossary_json, reason, status, prompt_version,
                            reviewed_model, review_result_json, review_fingerprint,
                            resolution_source, created_at, reviewed_at
                        )
                        SELECT ?, ?, review_type, candidate_kind, source_kind,
                               location, row_index, col_index, current_value, korean_text,
                               english_text, glossary_json, reason, status, prompt_version,
                               reviewed_model, review_result_json, review_fingerprint,
                               'identical_table_reuse', created_at, reviewed_at
                        FROM linguistic_review_candidates
                        WHERE run_id = ? AND table_id = ?
                          AND review_type IN ({type_placeholders})
                        """,
                        (
                            run_id,
                            mapping.target_table_id,
                            mapping.source_run_id,
                            mapping.source_table_id,
                            *check_types,
                        ),
                    )
        return copied

    def _finalize_run(
        self,
        *,
        run_id: int,
        selected_rule_keys: tuple[str, ...],
        mappings: list[ReusableTableValidation],
        reused_check_count: int,
    ) -> None:
        reused_report_ids = {item.source_report_id for item in mappings}
        all_keys = set(all_validation_rule_keys())
        scope_kind = (
            "shared"
            if mappings
            else "full"
            if set(selected_rule_keys) == all_keys
            else "selected"
        )
        base_run_id = mappings[0].source_run_id if mappings else None
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                refresh_run_issue_count(connection, run_id=run_id)
                connection.execute(
                    """
                    UPDATE validation_runs
                    SET scope_kind = ?, base_run_id = ?, selected_rules_json = ?,
                        reused_report_count = ?, reused_table_count = ?,
                        reused_check_count = ?
                    WHERE id = ?
                    """,
                    (
                        scope_kind,
                        base_run_id,
                        json.dumps(selected_rule_keys, ensure_ascii=False),
                        len(reused_report_ids),
                        len(mappings),
                        reused_check_count,
                        run_id,
                    ),
                )

    def _result_payload(
        self,
        *,
        report_id: int,
        run_id: int,
        selected_rule_keys: tuple[str, ...],
    ) -> dict[str, object]:
        with connect(self._db_path) as connection:
            init_db(connection)
            run = connection.execute(
                "SELECT * FROM validation_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            table_row = connection.execute(
                "SELECT COUNT(*) AS count FROM stat_tables WHERE report_id = ?",
                (report_id,),
            ).fetchone()
            language_row = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status <> 'reviewed' THEN 1 ELSE 0 END) AS pending,
                       SUM(CASE WHEN resolution_source <> '' THEN 1 ELSE 0 END) AS reused
                FROM linguistic_review_candidates
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            issues = validation_problem_count(connection, run_id=run_id)
        pending = int(language_row["pending"] or 0)
        return {
            "run_id": run_id,
            "report_id": report_id,
            "tables": int(table_row["count"] or 0),
            "issues": issues,
            "language_candidates": int(language_row["total"] or 0),
            "language_pending": pending,
            "language_reused": int(language_row["reused"] or 0),
            "language_status": (
                LanguageReviewStatus.COMPLETED
                if pending == 0
                else LanguageReviewStatus.PENDING
            ),
            "selected_rule_keys": list(selected_rule_keys),
            "reused_report_count": int(run["reused_report_count"] or 0),
            "reused_table_count": int(run["reused_table_count"] or 0),
            "reused_check_count": int(run["reused_check_count"] or 0),
        }


def latest_compatible_run(
    connection: DatabaseConnection,
    report_id: int,
    selected_rule_keys: tuple[str, ...],
) -> DatabaseRow | None:
    requested = set(selected_rule_keys)
    rows = connection.execute(
        """
        SELECT *
        FROM validation_runs
        WHERE report_id = ?
        ORDER BY completed_at DESC, id DESC
        """,
        (report_id,),
    ).fetchall()
    for row in rows:
        if requested.issubset(run_rule_keys(row)):
            return row
    return None


def run_rule_keys(run: DatabaseRow) -> tuple[str, ...]:
    raw = str(run["selected_rules_json"] or "[]")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = []
    if not isinstance(parsed, list) or not parsed:
        return all_validation_rule_keys()
    return normalize_validation_rule_keys(str(value) for value in parsed)
