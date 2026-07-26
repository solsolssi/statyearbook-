from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db.connection import connect
from app.db.schema import init_db
from app.operations.metrics import OperationsMetricsService, timestamp


class OperationsMetricsTest(unittest.TestCase):
    def test_jobs_stages_and_llm_usage_are_aggregated(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "operations.sqlite"
            now = datetime.now()
            with connect(db_path) as connection:
                init_db(connection)
                report_id = connection.execute(
                    """
                    INSERT INTO annual_reports (
                        year, title, source_file_name, source_file_path,
                        file_hash, imported_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (2026, "2026 연보", "2026.xlsx", "", "ops-report", timestamp(now)),
                ).lastrowid
                run_id = connection.execute(
                    """
                    INSERT INTO validation_runs (
                        report_id, rules_version, started_at, completed_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        report_id,
                        "test",
                        timestamp(now - timedelta(minutes=3)),
                        timestamp(now),
                    ),
                ).lastrowid
                completed_job = self._insert_job(
                    connection,
                    report_id=int(report_id),
                    status="completed",
                    created_at=timestamp(now - timedelta(hours=2)),
                    started_at=timestamp(now - timedelta(minutes=10)),
                    completed_at=timestamp(now - timedelta(minutes=5)),
                )
                failed_job = self._insert_job(
                    connection,
                    report_id=int(report_id),
                    status="failed",
                    created_at=timestamp(now - timedelta(hours=1)),
                    started_at=timestamp(now - timedelta(minutes=4)),
                    completed_at=timestamp(now - timedelta(minutes=2)),
                )
                connection.execute(
                    """
                    INSERT INTO report_processing_stages (
                        job_id, stage_name, status, started_at, completed_at
                    ) VALUES (?, 'import', 'completed', ?, ?)
                    """,
                    (
                        completed_job,
                        timestamp(now - timedelta(minutes=10)),
                        timestamp(now - timedelta(minutes=9)),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO report_processing_stages (
                        job_id, stage_name, status, started_at, completed_at
                    ) VALUES (?, 'import', 'failed', ?, ?)
                    """,
                    (
                        failed_job,
                        timestamp(now - timedelta(minutes=4)),
                        timestamp(now - timedelta(minutes=2)),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO llm_usage_events (
                        run_id, provider, model, request_kind,
                        input_tokens, output_tokens, total_tokens,
                        estimated_cost_usd
                    ) VALUES (?, 'bizrouter', 'gpt-5-mini', 'language_review',
                              100, 25, 125, 0.01)
                    """,
                    (run_id,),
                )
                connection.commit()

            overview = OperationsMetricsService(db_path).overview(
                window_days=7,
                report_id=int(report_id),
            )

            self.assertEqual(overview.jobs.total, 2)
            self.assertEqual(overview.jobs.completed, 1)
            self.assertEqual(overview.jobs.failed, 1)
            self.assertEqual(overview.jobs.failure_rate_percent, 50)
            self.assertEqual(overview.jobs.average_duration_seconds, 210)
            self.assertEqual(len(overview.stages), 1)
            self.assertEqual(overview.stages[0].failure_rate_percent, 50)
            self.assertEqual(overview.stages[0].average_duration_seconds, 90)
            self.assertEqual(overview.llm_total_tokens, 125)
            self.assertEqual(overview.llm_estimated_cost_usd, 0.01)

    @staticmethod
    def _insert_job(
        connection,
        *,
        report_id: int,
        status: str,
        created_at: str,
        started_at: str,
        completed_at: str,
    ) -> int:
        return int(
            connection.execute(
                """
                INSERT INTO report_processing_jobs (
                    report_id, source_file_name, source_file_path,
                    source_type, report_year, report_title, status,
                    current_stage, created_at, updated_at, started_at, completed_at
                ) VALUES (?, ?, ?, 'xlsx', 2026, '2026 연보', ?,
                          'completed', ?, ?, ?, ?)
                """,
                (
                    report_id,
                    f"{status}.xlsx",
                    f"/tmp/{status}.xlsx",
                    status,
                    created_at,
                    created_at,
                    started_at,
                    completed_at,
                ),
            ).lastrowid
        )


if __name__ == "__main__":
    unittest.main()
