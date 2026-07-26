from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.db.connection import connect
from app.db.schema import init_db
from app.domain.enums import Severity, ValidationStatus
from app.domain.validation import ValidationResult
from app.validation.repository import ValidationRepository
from app.validation.result_repository import (
    delete_validation_result,
    refresh_run_issue_count,
    update_validation_result_outcome,
    upsert_validation_result,
)


class ValidationResultRepositoryTests(unittest.TestCase):
    def test_validation_checks_are_the_only_persisted_result_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "report.sqlite"
            report_id, table_id = self._seed_report(db_path)

            run_id = ValidationRepository(db_path).save_run(
                report_id=report_id,
                rules_version="test-v1",
                issues=[],
                checks=[
                    ValidationResult(
                        table_id=table_id,
                        rule_id="test.pass",
                        check_type="합계 검수",
                        check_label="통과 검수",
                        location="1행 2열",
                        row_index=0,
                        col_index=1,
                        current_value="3",
                        expected_value="3",
                        difference="0",
                        status=ValidationStatus.NORMAL,
                        severity=Severity.INFO,
                        detail="정상",
                    ),
                    ValidationResult(
                        table_id=table_id,
                        rule_id="test.fail",
                        check_type="합계 검수",
                        check_label="미통과 검수",
                        location="2행 2열",
                        row_index=1,
                        col_index=1,
                        current_value="4",
                        expected_value="5",
                        difference="-1",
                        status=ValidationStatus.SUSPECTED_ERROR,
                        severity=Severity.CRITICAL,
                        detail="불일치",
                    ),
                ],
            )

            with connect(db_path) as connection:
                init_db(connection)
                check_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM validation_checks WHERE run_id = ?",
                    (run_id,),
                ).fetchone()["count"]
                issue_view_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM validation_issues WHERE run_id = ?",
                    (run_id,),
                ).fetchone()["count"]
                stored_issue_count = connection.execute(
                    "SELECT issue_count FROM validation_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()["issue_count"]
                object_type = connection.execute(
                    "SELECT type FROM sqlite_master WHERE name = 'validation_issues'"
                ).fetchone()["type"]

            self.assertEqual(check_count, 2)
            self.assertEqual(issue_view_count, 1)
            self.assertEqual(stored_issue_count, 1)
            self.assertEqual(object_type, "view")

    def test_language_and_blue_results_share_upsert_and_outcome_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "report.sqlite"
            report_id, table_id = self._seed_report(db_path)
            run_id = ValidationRepository(db_path).save_run(
                report_id=report_id,
                rules_version="test-v1",
                issues=[],
            )
            pending = ValidationResult(
                table_id=table_id,
                rule_id="source.blue_text_review",
                check_type="파란색 표기 확인",
                check_label="파란색 표기",
                location="1행 1열",
                row_index=0,
                col_index=0,
                current_value="검수 대상",
                expected_value="언어 검수 대기",
                difference="대기",
                status=ValidationStatus.NEEDS_REVIEW,
                severity=Severity.WARNING,
                detail="대기",
            )
            reviewed = ValidationResult(
                **{
                    **pending.__dict__,
                    "expected_value": "검수 대상",
                    "difference": "통과",
                    "status": ValidationStatus.NORMAL,
                    "severity": Severity.INFO,
                    "detail": "정상",
                }
            )

            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    self.assertTrue(
                        upsert_validation_result(
                            connection,
                            run_id=run_id,
                            result=pending,
                        )
                    )
                    self.assertFalse(
                        upsert_validation_result(
                            connection,
                            run_id=run_id,
                            result=reviewed,
                        )
                    )
                    update_validation_result_outcome(
                        connection,
                        run_id=run_id,
                        table_id=table_id,
                        rule_id=reviewed.rule_id,
                        location=reviewed.location,
                        current_value=reviewed.current_value,
                        expected_value="수정 제안",
                        difference="확인",
                        status=ValidationStatus.SUSPECTED_ERROR,
                        severity=Severity.CRITICAL.value,
                        detail="불일치",
                    )
                    refresh_run_issue_count(connection, run_id=run_id)

                rows = connection.execute(
                    "SELECT * FROM validation_checks WHERE run_id = ?",
                    (run_id,),
                ).fetchall()
                stored_count = connection.execute(
                    "SELECT issue_count FROM validation_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()["issue_count"]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["status"], "오류 의심")
                self.assertEqual(stored_count, 1)

                with connection:
                    deleted = delete_validation_result(
                        connection,
                        run_id=run_id,
                        table_id=table_id,
                        rule_id=reviewed.rule_id,
                        location=reviewed.location,
                        current_value=reviewed.current_value,
                    )
                    refresh_run_issue_count(connection, run_id=run_id)
                self.assertEqual(deleted, 1)
                self.assertEqual(
                    connection.execute(
                        "SELECT issue_count FROM validation_runs WHERE id = ?",
                        (run_id,),
                    ).fetchone()["issue_count"],
                    0,
                )

    @staticmethod
    def _seed_report(db_path: Path) -> tuple[int, int]:
        with connect(db_path) as connection:
            init_db(connection)
            report_id = connection.execute(
                """
                INSERT INTO annual_reports (
                    year, title, source_file_name, source_file_path, file_hash, imported_at
                ) VALUES (2026, '테스트 연보', 'test.xlsx', '/tmp/test.xlsx', 'test-hash', '2026-01-01')
                """
            ).lastrowid
            table_id = connection.execute(
                """
                INSERT INTO stat_tables (
                    report_id, code, title, unit, base_date, source
                ) VALUES (?, '1-1', '테스트 표', '명', '2025. 12. 31.', '테스트과')
                """,
                (report_id,),
            ).lastrowid
            return int(report_id), int(table_id)


if __name__ == "__main__":
    unittest.main()
