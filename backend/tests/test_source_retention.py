from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.core.config import Settings
from app.db.connection import connect
from app.db.schema import init_db
from app.operations.retention import SourceRetentionService


class FakeStorage:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete(self, object_key: str) -> None:
        self.deleted.append(object_key)


class SourceRetentionTest(unittest.TestCase):
    def test_dry_run_preserves_sources_and_apply_removes_expired_source(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "retention.sqlite"
            source_path = str(Path(directory) / "old.xlsx")
            Path(source_path).write_bytes(b"fixture")
            completed_at = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
            with connect(db_path) as connection:
                init_db(connection)
                report_id = connection.execute(
                    """
                    INSERT INTO annual_reports (
                        year, title, source_file_name, source_file_path,
                        file_hash, imported_at
                    ) VALUES (2026, '2026 연보', 'old.xlsx', ?, 'retention-report', ?)
                    """,
                    (source_path, completed_at),
                ).lastrowid
                job_id = connection.execute(
                    """
                    INSERT INTO report_processing_jobs (
                        report_id, source_file_name, source_file_path,
                        source_storage, source_object_key, source_type,
                        report_year, report_title, status, current_stage,
                        created_at, updated_at, completed_at
                    ) VALUES (?, 'old.xlsx', ?, 'local', ?, 'xlsx',
                              2026, '2026 연보', 'completed', 'completed',
                              ?, ?, ?)
                    """,
                    (
                        report_id,
                        source_path,
                        source_path,
                        completed_at,
                        completed_at,
                        completed_at,
                    ),
                ).lastrowid
                connection.commit()

            storage = FakeStorage()
            service = SourceRetentionService(
                db_path,
                settings=Settings(
                    completed_source_retention_days=30,
                    failed_source_retention_days=30,
                ),
                storage_factory=lambda _settings, _kind: storage,  # type: ignore[arg-type]
            )

            preview = service.prune(dry_run=True)
            self.assertEqual(preview.candidates, 1)
            self.assertEqual(storage.deleted, [])

            applied = service.prune(dry_run=False)
            self.assertEqual(applied.deleted, 1)
            self.assertEqual(storage.deleted, [source_path])
            with connect(db_path) as connection:
                job = connection.execute(
                    """
                    SELECT source_storage, source_file_path, source_object_key
                    FROM report_processing_jobs WHERE id = ?
                    """,
                    (job_id,),
                ).fetchone()
                report = connection.execute(
                    "SELECT source_file_path FROM annual_reports WHERE id = ?",
                    (report_id,),
                ).fetchone()
            self.assertEqual(job["source_storage"], "deleted")
            self.assertEqual(job["source_file_path"], "")
            self.assertEqual(job["source_object_key"], "")
            self.assertEqual(report["source_file_path"], "")


if __name__ == "__main__":
    unittest.main()
