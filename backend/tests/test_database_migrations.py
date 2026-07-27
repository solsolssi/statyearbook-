from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.db.connection import connect
from app.db.migrations import ensure_database_ready, reset_initialization_cache


class DatabaseMigrationsTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_initialization_cache()

    def test_initialization_is_cached_per_sqlite_database(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                ensure_database_ready(connection)

            with connect(db_path) as connection, patch(
                "app.db.migrations.schema.create_schema"
            ) as create_schema:
                ensure_database_ready(connection)
                create_schema.assert_not_called()

    def test_schema_and_data_migration_history_are_both_created(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                ensure_database_ready(connection)
                table = connection.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'annual_reports'"
                ).fetchone()
                series_tables = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM sqlite_master
                    WHERE type = 'table' AND name IN (
                        'series_import_batches',
                        'statistical_datasets',
                        'statistical_dataset_versions',
                        'statistical_observations',
                        'yearbook_table_recipes'
                    )
                    """
                ).fetchone()
                migration_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM schema_migrations"
                ).fetchone()

            self.assertIsNotNone(table)
            assert series_tables is not None
            self.assertEqual(int(series_tables["count"]), 5)
            assert migration_count is not None
            self.assertGreater(int(migration_count["count"]), 0)


if __name__ == "__main__":
    unittest.main()
