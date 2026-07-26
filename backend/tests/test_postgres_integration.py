from __future__ import annotations

import os
import unittest

from app.db.postgres import PostgresConnection
from app.domain.enums import Severity, ValidationStatus
from app.domain.validation import ValidationResult
from app.validation.result_repository import (
    refresh_run_issue_count,
    upsert_validation_result,
)


@unittest.skipUnless(
    os.getenv("TEST_DATABASE_URL"),
    "TEST_DATABASE_URL이 설정된 전용 PostgreSQL에서만 실행합니다.",
)
class PostgresIntegrationTest(unittest.TestCase):
    """Exercise the real driver without ever falling back to production DATABASE_URL."""

    def test_qmark_queries_and_mapping_rows(self) -> None:
        database_url = os.environ["TEST_DATABASE_URL"]
        with PostgresConnection(database_url) as connection:
            connection.execute(
                """
                CREATE TEMP TABLE validation_connection_probe (
                    id SERIAL PRIMARY KEY,
                    label TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO validation_connection_probe (label) VALUES (?)",
                ("연결 확인",),
            )
            row = connection.execute(
                "SELECT id, label FROM validation_connection_probe WHERE label = ?",
                ("연결 확인",),
            ).fetchone()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["label"], "연결 확인")
        self.assertGreater(int(row["id"]), 0)

    def test_canonical_validation_result_repository_on_postgres(self) -> None:
        database_url = os.environ["TEST_DATABASE_URL"]
        with PostgresConnection(database_url) as connection:
            connection.execute(
                """
                CREATE TEMP TABLE validation_runs (
                    id INTEGER PRIMARY KEY,
                    issue_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.execute(
                """
                CREATE TEMP TABLE validation_checks (
                    id SERIAL PRIMARY KEY,
                    run_id INTEGER NOT NULL,
                    table_id INTEGER NOT NULL,
                    profile_id INTEGER,
                    rule_id TEXT NOT NULL,
                    check_type TEXT NOT NULL,
                    check_label TEXT NOT NULL,
                    location TEXT NOT NULL,
                    row_index INTEGER,
                    col_index INTEGER,
                    current_value TEXT NOT NULL DEFAULT '',
                    expected_value TEXT,
                    difference TEXT,
                    status TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    formula TEXT,
                    confidence REAL
                )
                """
            )
            connection.execute(
                "INSERT INTO validation_runs (id, issue_count) VALUES (?, ?)",
                (101, 0),
            )
            inserted = upsert_validation_result(
                connection,
                run_id=101,
                result=ValidationResult(
                    table_id=201,
                    rule_id="postgres.sum",
                    check_type="합계 검수",
                    check_label="PostgreSQL 합계",
                    location="1행 2열",
                    row_index=0,
                    col_index=1,
                    current_value="9",
                    expected_value="10",
                    difference="-1",
                    status=ValidationStatus.SUSPECTED_ERROR,
                    severity=Severity.CRITICAL,
                    detail="불일치",
                ),
            )
            issue_count = refresh_run_issue_count(connection, run_id=101)
            row = connection.execute(
                """
                SELECT check_result.status, run.issue_count
                FROM validation_checks check_result
                JOIN validation_runs run ON run.id = check_result.run_id
                WHERE check_result.rule_id = ?
                """,
                ("postgres.sum",),
            ).fetchone()

        self.assertTrue(inserted)
        self.assertEqual(issue_count, 1)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["status"], "오류 의심")
        self.assertEqual(row["issue_count"], 1)


if __name__ == "__main__":
    unittest.main()
