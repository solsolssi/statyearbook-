from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.db.connection import connect
from app.db.schema import init_db
from app.services.validation_execution_service import ValidationExecutionService


class ValidationExecutionServiceTest(unittest.TestCase):
    def test_selected_checks_reuse_only_identical_tables_from_explicit_base(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    donor_report = insert_report(connection, year=2026, title="검수 기준")
                    target_report = insert_report(
                        connection,
                        year=2026,
                        title="업로드 수정본",
                        base_report_id=donor_report,
                    )
                    donor_same = insert_table(
                        connection,
                        report_id=donor_report,
                        code="1-1",
                        values=("구분", "합계", "계", "3"),
                    )
                    insert_table(
                        connection,
                        report_id=target_report,
                        code="1-1",
                        values=("구분", "합계", "계", "3"),
                    )
                    donor_changed = insert_table(
                        connection,
                        report_id=donor_report,
                        code="1-2",
                        values=("구분", "합계", "계", "4"),
                    )
                    insert_table(
                        connection,
                        report_id=target_report,
                        code="1-2",
                        values=("구분", "합계", "계", "5"),
                    )
                    donor_run = int(
                        connection.execute(
                            """
                            INSERT INTO validation_runs (
                                report_id, rules_version, started_at, completed_at,
                                selected_rules_json
                            ) VALUES (?, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
                            """,
                            (donor_report, json.dumps(["sum", "ratio"])),
                        ).lastrowid
                    )
                    insert_check(
                        connection,
                        run_id=donor_run,
                        table_id=donor_same,
                        check_type="합계 검수",
                    )
                    insert_check(
                        connection,
                        run_id=donor_run,
                        table_id=donor_same,
                        check_type="비율 검수",
                    )
                    insert_check(
                        connection,
                        run_id=donor_run,
                        table_id=donor_changed,
                        check_type="합계 검수",
                    )

            service = ValidationExecutionService(db_path)
            result = service.run(
                report_id=target_report,
                selected_rule_keys=["sum"],
                reuse_existing=True,
            )

            self.assertEqual(result["selected_rule_keys"], ["sum"])
            self.assertEqual(result["reused_report_count"], 1)
            self.assertEqual(result["reused_table_count"], 1)
            with connect(db_path) as connection:
                checks = connection.execute(
                    """
                    SELECT t.code, c.check_type
                    FROM validation_checks c
                    JOIN stat_tables t ON t.id = c.table_id
                    WHERE c.run_id = ?
                    ORDER BY t.code, c.check_type
                    """,
                    (result["run_id"],),
                ).fetchall()
            same_table_types = [
                str(row["check_type"])
                for row in checks
                if str(row["code"]) == "1-1"
            ]
            self.assertEqual(same_table_types, ["합계 검수"])
            self.assertFalse(
                any(
                    str(row["code"]) == "1-2"
                    and str(row["check_type"]) == "비율 검수"
                    for row in checks
                )
            )

            repeated = service.run(
                report_id=target_report,
                selected_rule_keys=["sum"],
                reuse_existing=True,
            )
            self.assertEqual(repeated["run_id"], result["run_id"])

    def test_same_year_unrelated_report_never_reuses_validation(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    donor_report = insert_report(connection, year=2026, title="다른 연보")
                    target_report = insert_report(connection, year=2026, title="독립 연보")
                    donor_table = insert_table(
                        connection, report_id=donor_report, code="1-1", values=("구분", "합계", "계", "3")
                    )
                    insert_table(
                        connection, report_id=target_report, code="1-1", values=("구분", "합계", "계", "3")
                    )
                    donor_run = int(connection.execute(
                        """
                        INSERT INTO validation_runs (
                            report_id, rules_version, started_at, completed_at, selected_rules_json
                        ) VALUES (?, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
                        """,
                        (donor_report, json.dumps(["sum"])),
                    ).lastrowid)
                    insert_check(connection, run_id=donor_run, table_id=donor_table, check_type="합계 검수")

            result = ValidationExecutionService(db_path).run(
                report_id=target_report,
                selected_rule_keys=["sum"],
                reuse_existing=True,
            )
            self.assertEqual(result["reused_report_count"], 0)
            self.assertEqual(result["reused_table_count"], 0)

    def test_explicit_validation_run_reuses_visible_report_when_compatible(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    donor_report = insert_report(connection, year=2026, title="2026 기준 연보")
                    target_report = insert_report(connection, year=2027, title="2027 수정 연보")
                    donor_table = insert_table(
                        connection,
                        report_id=donor_report,
                        code="1-1",
                        values=("구분", "합계", "계", "3"),
                    )
                    insert_table(
                        connection,
                        report_id=target_report,
                        code="1-1",
                        values=("구분", "합계", "계", "3"),
                    )
                    donor_run = int(connection.execute(
                        """
                        INSERT INTO validation_runs (
                            report_id, rules_version, started_at, completed_at, selected_rules_json
                        ) VALUES (?, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
                        """,
                        (donor_report, json.dumps(["sum", "ratio"])),
                    ).lastrowid)
                    insert_check(connection, run_id=donor_run, table_id=donor_table, check_type="합계 검수")
                    target_run = int(connection.execute(
                        """
                        INSERT INTO validation_runs (
                            report_id, rules_version, started_at, completed_at, selected_rules_json
                        ) VALUES (?, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
                        """,
                        (target_report, json.dumps(["sum", "ratio"])),
                    ).lastrowid)

            service = ValidationExecutionService(db_path)
            reusable_runs = service.list_reusable_runs(target_report)
            self.assertEqual([item["id"] for item in reusable_runs], [target_run, donor_run])

            result = service.run(
                report_id=target_report,
                selected_rule_keys=["sum"],
                reuse_existing=True,
                source_validation_run_id=donor_run,
            )
            self.assertEqual(result["reused_report_count"], 1)
            self.assertEqual(result["reused_table_count"], 1)
            with connect(db_path) as connection:
                run = connection.execute(
                    "SELECT base_run_id FROM validation_runs WHERE id = ?",
                    (result["run_id"],),
                ).fetchone()
            self.assertEqual(int(run["base_run_id"]), donor_run)

            with self.assertRaisesRegex(ValueError, "모두 포함"):
                service.run(
                    report_id=target_report,
                    selected_rule_keys=["spelling"],
                    reuse_existing=True,
                    source_validation_run_id=donor_run,
                )

    def test_explicit_validation_run_can_reuse_same_report_previous_run(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = insert_report(connection, year=2026, title="2026 연보")
                    table_id = insert_table(
                        connection,
                        report_id=report_id,
                        code="1-1",
                        values=("구분", "합계", "계", "3"),
                    )
                    source_run = int(connection.execute(
                        """
                        INSERT INTO validation_runs (
                            report_id, rules_version, started_at, completed_at, selected_rules_json
                        ) VALUES (?, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
                        """,
                        (report_id, json.dumps(["sum", "ratio"])),
                    ).lastrowid)
                    insert_check(connection, run_id=source_run, table_id=table_id, check_type="합계 검수")
                    insert_check(
                        connection,
                        run_id=source_run,
                        table_id=table_id,
                        check_type="비율 검수",
                        status="확인 필요",
                    )
                    duplicate_run = int(connection.execute(
                        """
                        INSERT INTO validation_runs (
                            report_id, rules_version, started_at, completed_at, selected_rules_json
                        ) VALUES (?, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
                        """,
                        (report_id, json.dumps(["sum", "ratio"])),
                    ).lastrowid)
                    insert_check(connection, run_id=duplicate_run, table_id=table_id, check_type="합계 검수")
                    insert_check(
                        connection,
                        run_id=duplicate_run,
                        table_id=table_id,
                        check_type="비율 검수",
                        status="확인 필요",
                    )

            service = ValidationExecutionService(db_path)
            reusable_runs = service.list_reusable_runs(report_id)
            self.assertEqual([item["id"] for item in reusable_runs], [source_run])
            self.assertEqual(reusable_runs[0]["normal_count"], 0)
            self.assertEqual(reusable_runs[0]["needs_review_count"], 1)
            self.assertEqual(reusable_runs[0]["suspected_error_count"], 0)

            result = service.run(
                report_id=report_id,
                selected_rule_keys=["sum"],
                reuse_existing=True,
                source_validation_run_id=source_run,
            )
            self.assertEqual(result["reused_report_count"], 1)
            self.assertEqual(result["reused_table_count"], 1)
            self.assertGreater(result["reused_check_count"], 0)

            exact_result = service.run(
                report_id=report_id,
                selected_rule_keys=["sum", "ratio"],
                reuse_existing=True,
                source_validation_run_id=source_run,
            )
            self.assertEqual(exact_result["run_id"], source_run)

    def test_same_report_revalidates_only_table_edited_after_selected_run(self) -> None:
        """An edit must not copy a prior result from the same mutable row."""

        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = insert_report(connection, year=2026, title="테스트 연보")
                    unchanged_table = insert_table(
                        connection,
                        report_id=report_id,
                        code="1-1-1",
                        values=("구분", "합계", "계", "3"),
                    )
                    edited_table = insert_table(
                        connection,
                        report_id=report_id,
                        code="1-1-2",
                        values=("구분", "합계", "계", "4"),
                    )
                    source_run = int(connection.execute(
                        """
                        INSERT INTO validation_runs (
                            report_id, rules_version, started_at, completed_at,
                            selected_rules_json
                        ) VALUES (?, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
                        """,
                        (report_id, json.dumps(["sum"])),
                    ).lastrowid)
                    insert_check(
                        connection,
                        run_id=source_run,
                        table_id=unchanged_table,
                        check_type="합계 검수",
                    )
                    insert_check(
                        connection,
                        run_id=source_run,
                        table_id=edited_table,
                        check_type="합계 검수",
                    )
                    connection.execute(
                        """
                        UPDATE stat_tables
                        SET edited_after_run_id = ?
                        WHERE id = ?
                        """,
                        (source_run, edited_table),
                    )

            result = ValidationExecutionService(db_path).run(
                report_id=report_id,
                selected_rule_keys=["sum"],
                reuse_existing=True,
                source_validation_run_id=source_run,
            )

            self.assertNotEqual(result["run_id"], source_run)
            self.assertEqual(result["reused_report_count"], 1)
            self.assertEqual(result["reused_table_count"], 1)
            with connect(db_path) as connection:
                copied = connection.execute(
                    """
                    SELECT t.code
                    FROM validation_checks c
                    JOIN stat_tables t ON t.id = c.table_id
                    WHERE c.run_id = ? AND c.rule_id = 'test.합계 검수'
                    ORDER BY t.code
                    """,
                    (result["run_id"],),
                ).fetchall()
            self.assertEqual([str(row["code"]) for row in copied], ["1-1-1"])

    def test_reusable_run_counts_pending_language_without_multiplying_rows(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = insert_report(connection, year=2026, title="2026 연보")
                    table_id = insert_table(
                        connection,
                        report_id=report_id,
                        code="1-1",
                        values=("구분", "합계", "계", "3"),
                    )
                    run_id = int(connection.execute(
                        """
                        INSERT INTO validation_runs (
                            report_id, rules_version, started_at, completed_at, selected_rules_json
                        ) VALUES (?, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
                        """,
                        (report_id, json.dumps(["sum", "translation"])),
                    ).lastrowid)
                    insert_check(connection, run_id=run_id, table_id=table_id, check_type="합계 검수")
                    insert_check(connection, run_id=run_id, table_id=table_id, check_type="합계 검수")
                    connection.executemany(
                        """
                        INSERT INTO linguistic_review_candidates (
                            run_id, table_id, review_type, candidate_kind,
                            source_kind, location, current_value, korean_text,
                            english_text, glossary_json, reason, prompt_version
                        ) VALUES (?, ?, '번역 검수', 'translation_pair',
                                  'document', ?, ?, ?, ?, '[]', '후보', 'test')
                        """,
                        [
                            (run_id, table_id, "2행 1열", "정부 Government", "정부", "Government"),
                            (run_id, table_id, "3행 1열", "조직 Organization", "조직", "Organization"),
                        ],
                    )

            reusable_runs = ValidationExecutionService(db_path).list_reusable_runs(report_id)

            self.assertEqual(len(reusable_runs), 1)
            self.assertEqual(reusable_runs[0]["id"], run_id)
            self.assertEqual(reusable_runs[0]["normal_count"], 0)
            self.assertEqual(reusable_runs[0]["needs_review_count"], 1)
            self.assertEqual(reusable_runs[0]["suspected_error_count"], 0)

    def test_language_llm_can_resume_pending_candidates_without_recalculating(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = insert_report(connection, year=2027, title="언어 재검수 연보")
                    table_id = insert_table(
                        connection,
                        report_id=report_id,
                        code="1-1-1",
                        values=("구분", "합계", "정부 Government", "3"),
                    )
                    run_id = int(connection.execute(
                        """
                        INSERT INTO validation_runs (
                            report_id, rules_version, started_at, completed_at,
                            selected_rules_json
                        ) VALUES (?, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
                        """,
                        (report_id, json.dumps(["sum", "translation"])),
                    ).lastrowid)
                    insert_check(connection, run_id=run_id, table_id=table_id, check_type="합계 검수")
                    connection.execute(
                        """
                        INSERT INTO linguistic_review_candidates (
                            run_id, table_id, review_type, candidate_kind,
                            source_kind, location, current_value, korean_text,
                            english_text, glossary_json, reason, prompt_version
                        ) VALUES (?, ?, '번역 검수', 'translation_pair',
                                  'document', '2행 1열', '정부 Government',
                                  '정부', 'Government', '[]', '후보', 'test')
                        """,
                        (run_id, table_id),
                    )

            service = ValidationExecutionService(db_path)
            with patch.object(service, "_run_pending_llm_reviews") as resume:
                result = service.run(
                    report_id=report_id,
                    selected_rule_keys=["sum", "translation"],
                    reuse_existing=True,
                    include_language_llm=True,
                    source_validation_run_id=run_id,
                )

            self.assertEqual(result["run_id"], run_id)
            resume.assert_called_once_with(run_id)

def insert_report(
    connection,
    *,
    year: int,
    title: str,
    base_report_id: int | None = None,
) -> int:  # type: ignore[no-untyped-def]
    return int(
        connection.execute(
            """
            INSERT INTO annual_reports (
                year, title, source_file_name, source_file_path,
                file_hash, imported_at, base_report_id
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
            """,
            (year, title, f"{title}.xlsx", f"/tmp/{title}.xlsx", f"hash-{title}", base_report_id),
        ).lastrowid
    )


def insert_table(  # type: ignore[no-untyped-def]
    connection,
    *,
    report_id: int,
    code: str,
    values: tuple[str, ...],
) -> int:
    table_id = int(
        connection.execute(
            """
            INSERT INTO stat_tables (
                report_id, code, title, section_title, unit, base_date,
                source, note, table_order
            ) VALUES (?, ?, ?, ?, '명', '2025. 12. 31.', '테스트과', '', 1)
            """,
            (report_id, code, f"{code} 테스트", f"{code} 테스트"),
        ).lastrowid
    )
    connection.executemany(
        """
        INSERT INTO stat_table_cells (
            table_id, row_index, col_index, text_value, numeric_value, is_header
        ) VALUES (?, ?, ?, ?, NULL, ?)
        """,
        [
            (table_id, index // 2, index % 2, value, int(index < 2))
            for index, value in enumerate(values)
        ],
    )
    return table_id


def insert_check(  # type: ignore[no-untyped-def]
    connection,
    *,
    run_id: int,
    table_id: int,
    check_type: str,
    status: str = "정상",
) -> None:
    severity = "info" if status == "정상" else "warning" if status == "확인 필요" else "critical"
    connection.execute(
        """
        INSERT INTO validation_checks (
            run_id, table_id, rule_id, check_type, check_label,
            location, current_value, status, severity, detail
        ) VALUES (?, ?, ?, ?, ?, '2행 2열', '3', ?, ?, '테스트')
        """,
        (run_id, table_id, f"test.{check_type}", check_type, check_type, status, severity),
    )


if __name__ == "__main__":
    unittest.main()
