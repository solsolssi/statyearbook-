from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from app.db.connection import DB_PATH, DatabaseConnection, DatabaseRow, connect
from app.db.schema import init_db
from app.domain.enums import LanguageReviewStatus
from app.validation.calculation_workflow import CalculationValidationWorkflow
from app.validation.language_workflow import LanguageValidationWorkflow
from app.validation.report_lineage import report_lineage_ids
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

    Reuse is based on equal metadata and equal cell values inside an explicit
    base-report lineage.  A matching publication year has no reuse meaning.
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
        source_validation_run_id: int | None = None,
    ) -> dict[str, object]:
        rule_keys = normalize_validation_rule_keys(selected_rule_keys)
        report = self._repository.report(report_id)
        if report is None:
            raise ValueError("검수할 연보를 찾을 수 없습니다.")

        selected_source = (
            self._selected_source_run(
                target_report_id=report_id,
                source_validation_run_id=source_validation_run_id,
                selected_rule_keys=rule_keys,
            )
            if reuse_existing and source_validation_run_id is not None
            else None
        )
        if (
            reuse_existing
            and selected_source is not None
            and int(selected_source["report_id"]) == report_id
            and run_rule_keys(selected_source) == rule_keys
        ):
            if include_llm and self._has_pending_language_reviews(
                int(selected_source["id"]),
                selected_language_check_types(rule_keys),
            ):
                self._run_pending_llm_reviews(int(selected_source["id"]))
            return self._result_payload(
                report_id=report_id,
                run_id=int(selected_source["id"]),
                selected_rule_keys=rule_keys,
            )

        if reuse_existing and selected_source is None:
            existing = self._matching_current_run(report_id, rule_keys)
            if existing is not None:
                if include_llm and self._has_pending_language_reviews(
                    int(existing["id"]),
                    selected_language_check_types(rule_keys),
                ):
                    self._run_pending_llm_reviews(int(existing["id"]))
                return self._result_payload(
                    report_id=report_id,
                    run_id=int(existing["id"]),
                    selected_rule_keys=rule_keys,
                )

        reusable = (
            self._reusable_tables(report, rule_keys, selected_source=selected_source)
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
        if include_llm and language_types:
            # A revised report may have copied pending candidates from its base
            # report. Complete those in this run instead of creating another
            # full run or treating a prior same-year report as a cache source.
            self._run_pending_llm_reviews(run_id)
        self._finalize_run(
            run_id=run_id,
            selected_rule_keys=rule_keys,
            mappings=reusable,
            reused_check_count=reused_check_count,
            selected_source_run_id=(int(selected_source["id"]) if selected_source else None),
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
        *,
        selected_source: DatabaseRow | None = None,
    ) -> list[ReusableTableValidation]:
        report_id = int(report["id"])
        with connect(self._db_path) as connection:
            init_db(connection)
            # A manually selected execution is an explicit reuse source.
            # Without it, keep the existing base-report lineage behavior.
            candidates = (
                [(int(selected_source["report_id"]), selected_source)]
                if selected_source is not None
                else [
                    (
                        candidate_report_id,
                        latest_compatible_run(
                            connection, candidate_report_id, selected_rule_keys
                        ),
                    )
                    for candidate_report_id in report_lineage_ids(
                        connection, report_id, include_self=False
                    )
                ]
            )
            target_tables = tables_by_code(connection, report_id)
            resolved: dict[int, ReusableTableValidation] = {}
            for candidate_report_id, run in candidates:
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

    def _selected_source_run(
        self,
        *,
        target_report_id: int,
        source_validation_run_id: int,
        selected_rule_keys: tuple[str, ...],
    ) -> DatabaseRow:
        with connect(self._db_path) as connection:
            init_db(connection)
            row = connection.execute(
                "SELECT * FROM validation_runs WHERE id = ?",
                (source_validation_run_id,),
            ).fetchone()
        if row is None:
            raise ValueError("선택한 재사용 검수 실행을 찾을 수 없습니다.")
        if not set(selected_rule_keys).issubset(run_rule_keys(row)):
            raise ValueError(
                "선택한 재사용 검수 실행에 현재 선택한 검수 항목이 모두 포함되어 있지 않습니다."
            )
        return row

    def list_reusable_runs(self, target_report_id: int) -> list[dict[str, object]]:
        """List visible completed runs for explicit reuse, including the current report."""

        with connect(self._db_path) as connection:
            init_db(connection)
            rows = connection.execute(
                """
                WITH check_counts AS (
                    SELECT run_id, COUNT(*) AS check_count
                    FROM validation_checks
                    GROUP BY run_id
                )
                SELECT vr.id, vr.report_id, ar.year, ar.title, vr.completed_at,
                       vr.issue_count, vr.scope_kind, vr.selected_rules_json,
                       COALESCE(cc.check_count, 0) AS check_count
                FROM validation_runs vr
                JOIN annual_reports ar ON ar.id = vr.report_id
                LEFT JOIN check_counts cc ON cc.run_id = vr.id
                WHERE COALESCE(ar.is_archived, 0) = 0
                ORDER BY ar.year DESC, vr.completed_at DESC, vr.id DESC
                """,
            ).fetchall()
            table_status_rows = connection.execute(
                """
                SELECT
                    vr.id AS run_id,
                    st.code AS table_code,
                    MAX(CASE WHEN vc.status = '오류 의심' THEN 1 ELSE 0 END) AS has_error,
                    MAX(CASE WHEN vc.status = '확인 필요' THEN 1 ELSE 0 END) AS has_warning
                FROM validation_runs vr
                JOIN annual_reports ar ON ar.id = vr.report_id
                JOIN stat_tables st ON st.report_id = ar.id
                LEFT JOIN validation_checks vc
                  ON vc.run_id = vr.id AND vc.table_id = st.id
                WHERE COALESCE(ar.is_archived, 0) = 0
                GROUP BY vr.id, st.id
                """,
            ).fetchall()
        table_counts_by_run = logical_table_status_counts(table_status_rows)
        unique_rows = unique_reusable_run_rows(rows, table_counts_by_run, target_report_id)
        return [
            {
                "id": int(row["id"]),
                "report_id": int(row["report_id"]),
                "report_year": int(row["year"]),
                "report_title": str(row["title"]),
                "completed_at": str(row["completed_at"]),
                "issue_count": int(row["issue_count"] or 0),
                "normal_count": table_counts_by_run.get(int(row["id"]), {}).get("normal", 0),
                "needs_review_count": table_counts_by_run.get(int(row["id"]), {}).get("needs_review", 0),
                "suspected_error_count": table_counts_by_run.get(int(row["id"]), {}).get("suspected_error", 0),
                "scope_kind": str(row["scope_kind"] or "full"),
                "selected_rule_keys": list(run_rule_keys(row)),
            }
            for row in unique_rows
        ]

    def _has_pending_language_reviews(
        self,
        run_id: int,
        language_types: frozenset[str],
    ) -> bool:
        if not language_types:
            return False
        placeholders = ",".join("?" for _ in language_types)
        with connect(self._db_path) as connection:
            init_db(connection)
            row = connection.execute(
                f"""
                SELECT 1
                FROM linguistic_review_candidates
                WHERE run_id = ? AND status <> 'reviewed'
                  AND review_type IN ({placeholders})
                LIMIT 1
                """,
                (run_id, *sorted(language_types)),
            ).fetchone()
            return row is not None

    def _run_pending_llm_reviews(self, run_id: int) -> None:
        from app.validation.llm_translation_review import append_llm_translation_reviews
        from app.validation.blue_review import synchronize_blue_review_checks

        result = append_llm_translation_reviews(self._db_path, run_id=run_id, limit=None)
        if result.skipped_reason:
            raise RuntimeError(
                "LLM 전수 언어 검수가 실행되지 않았습니다: "
                f"{result.skipped_reason}"
            )
        # Existing runs may be resumed only for pending blue candidates.
        # Refresh their visible checks after the resumed LLM pass as well.
        synchronize_blue_review_checks(self._db_path, run_id=run_id)

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
        selected_source_run_id: int | None,
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
        base_run_id = (
            selected_source_run_id
            if selected_source_run_id is not None
            else mappings[0].source_run_id if mappings else None
        )
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


def unique_reusable_run_rows(
    rows: list[DatabaseRow],
    table_counts_by_run: dict[int, dict[str, int]],
    target_report_id: int,
) -> list[DatabaseRow]:
    """Collapse repeated executions with the same visible validation summary."""

    selected: dict[tuple[object, ...], DatabaseRow] = {}
    for row in sorted(rows, key=lambda item: int(item["id"])):
        counts = table_counts_by_run.get(int(row["id"]), {})
        signature = (
            int(row["report_id"]),
            tuple(run_rule_keys(row)),
            int(row["check_count"] or 0),
            int(counts.get("normal", 0)),
            int(counts.get("needs_review", 0)),
            int(counts.get("suspected_error", 0)),
        )
        selected.setdefault(signature, row)
    ordered = list(selected.values())
    ordered.sort(key=lambda item: (str(item["completed_at"] or ""), int(item["id"])), reverse=True)
    ordered.sort(key=lambda item: int(item["year"]), reverse=True)
    ordered.sort(key=lambda item: int(item["report_id"]) != target_report_id)
    return ordered


def logical_table_status_counts(rows: list[DatabaseRow]) -> dict[int, dict[str, int]]:
    status_by_run_and_table: dict[int, dict[str, str]] = {}
    for row in rows:
        run_id = int(row["run_id"])
        table_code = logical_table_code(str(row["table_code"] or ""))
        if not table_code:
            continue
        has_error = bool(int(row["has_error"] or 0))
        has_warning = bool(int(row["has_warning"] or 0))
        status = (
            "suspected_error"
            if has_error
            else "needs_review"
            if has_warning
            else "normal"
        )
        existing = status_by_run_and_table.setdefault(run_id, {}).get(table_code)
        if existing == "suspected_error" or (
            existing == "needs_review" and status == "normal"
        ):
            continue
        status_by_run_and_table[run_id][table_code] = status

    return {
        run_id: {
            "normal": sum(1 for status in table_statuses.values() if status == "normal"),
            "needs_review": sum(
                1 for status in table_statuses.values() if status == "needs_review"
            ),
            "suspected_error": sum(
                1 for status in table_statuses.values() if status == "suspected_error"
            ),
        }
        for run_id, table_statuses in status_by_run_and_table.items()
    }


def logical_table_code(value: str) -> str:
    return re.sub(r"\s+표\s*\d+$", "", value).strip()


def run_rule_keys(run: DatabaseRow) -> tuple[str, ...]:
    raw = str(run["selected_rules_json"] or "[]")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = []
    if not isinstance(parsed, list) or not parsed:
        return all_validation_rule_keys()
    return normalize_validation_rule_keys(str(value) for value in parsed)
