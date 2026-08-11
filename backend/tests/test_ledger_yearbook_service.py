from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from app.db.connection import connect
from app.db.schema import init_db
from app.services.ledger_yearbook_service import LedgerYearbookService
from app.services.database_report_service import DatabaseReportService


class LedgerYearbookServiceTest(unittest.TestCase):
    def test_completed_target_report_is_ignored_for_generation(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    batch = connection.execute(
                        """
                        INSERT INTO series_import_batches (
                            source_file_name, file_hash, import_kind, target_year
                        ) VALUES ('full.xlsx', 'full-layout', 'relational_full', 0)
                        """
                    )
                    batch_id = int(batch.lastrowid)
                    delta_batch = connection.execute(
                        """
                        INSERT INTO series_import_batches (
                            source_file_name, file_hash, import_kind, target_year
                        ) VALUES ('increment.xlsx', 'increment', 'relational_incremental', 2026)
                        """
                    )
                    delta_batch_id = int(delta_batch.lastrowid)
                    base = connection.execute(
                        """
                        INSERT INTO annual_reports (
                            year, title, source_file_name, source_file_path,
                            file_hash, imported_at, origin_kind
                        ) VALUES (2025, '기준', 'base.hwpx', '', 'base-layout',
                                  '2025-01-01', 'uploaded')
                        """
                    )
                    base_report_id = int(base.lastrowid)
                    target = connection.execute(
                        """
                        INSERT INTO annual_reports (
                            year, title, source_file_name, source_file_path,
                            file_hash, imported_at, origin_kind
                        ) VALUES (2026, '확정 형식', 'target.hwpx', '', 'target-layout',
                                  '2026-01-01', 'uploaded')
                        """
                    )
                    target_report_id = int(target.lastrowid)
                    for report_id, definitions in (
                        (base_report_id, (("X", "10"), ("DEL", "20"))),
                        (target_report_id, (("X", "999"), ("NEW", "888"))),
                    ):
                        for table_order, (code, value) in enumerate(definitions, 1):
                            table = connection.execute(
                                """
                                INSERT INTO stat_tables (
                                    report_id, code, title, table_order
                                ) VALUES (?, ?, ?, ?)
                                """,
                                (report_id, code, code, table_order),
                            )
                            table_id = int(table.lastrowid)
                            connection.executemany(
                                """
                                INSERT INTO stat_table_cells (
                                    table_id, row_index, col_index,
                                    text_value, is_header
                                ) VALUES (?, ?, ?, ?, ?)
                                """,
                                [
                                    (table_id, 0, 0, "구분", 1),
                                    (table_id, 0, 1, "값", 1),
                                    (table_id, 1, 0, "항목", 0),
                                    (table_id, 1, 1, value, 0),
                                ],
                            )

            generated = LedgerYearbookService(db_path).generate(
                base_report_id=base_report_id,
                target_year=2026,
                source_batch_id=batch_id,
                mode="append_year",
                title="형식 학습 결과",
            )
            with connect(db_path) as connection:
                cells = connection.execute(
                    """
                    SELECT table_row.code, cell.text_value
                    FROM stat_tables table_row
                    JOIN stat_table_cells cell ON cell.table_id = table_row.id
                    WHERE table_row.report_id = ?
                      AND cell.row_index = 1 AND cell.col_index = 1
                    ORDER BY table_row.code
                    """,
                    (generated.report_id,),
                ).fetchall()

            # The uploaded 2026 report is only a comparison oracle.  The
            # generated report must retain the selected 2025 predecessor's
            # structure and must not inherit NEW/DEL decisions from it.
            self.assertEqual(generated.new_table_count, 0)
            self.assertEqual(generated.deleted_table_count, 0)
            self.assertEqual(
                {str(row["code"]): str(row["text_value"] or "") for row in cells},
                {"DEL": "20", "X": "10"},
            )

    def test_generates_next_report_snapshot_with_a_shifted_year_window(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report = connection.execute(
                        """
                        INSERT INTO annual_reports (
                            year, title, source_file_name, source_file_path,
                            file_hash, imported_at, is_archived, is_template
                        ) VALUES (2025, '기준', 'base.md', '', 'base', '2025-01-01', 1, 1)
                        """
                    )
                    report_id = int(report.lastrowid)
                    table = connection.execute(
                        """
                        INSERT INTO stat_tables (
                            report_id, code, title, table_order
                        ) VALUES (?, '9-9-9', '연도별 테스트', 1)
                        """,
                        (report_id,),
                    )
                    table_id = int(table.lastrowid)
                    for row_index, row in enumerate(
                        [["연도", "값"], ["2023", "10"], ["2024", "20"]]
                    ):
                        for col_index, value in enumerate(row):
                            connection.execute(
                                """
                                INSERT INTO stat_table_cells (
                                    table_id, row_index, col_index, text_value, is_header
                                ) VALUES (?, ?, ?, ?, ?)
                                """,
                                (table_id, row_index, col_index, value, int(row_index == 0)),
                            )
                    batch = connection.execute(
                        """
                        INSERT INTO series_import_batches (
                            source_file_name, file_hash, import_kind, target_year
                        ) VALUES ('source.xlsx', 'source', 'relational_full', 0)
                        """
                    )
                    batch_id = int(batch.lastrowid)
                    delta_batch = connection.execute(
                        """
                        INSERT INTO series_import_batches (
                            source_file_name, file_hash, import_kind, target_year
                        ) VALUES ('increment.xlsx', 'increment-window', 'relational_incremental', 2026)
                        """
                    )
                    delta_batch_id = int(delta_batch.lastrowid)
                    dataset = connection.execute(
                        """
                        INSERT INTO statistical_datasets (
                            source_key, external_id, title
                        ) VALUES ('M-TEST', 'M-TEST', '연도별 테스트')
                        """
                    )
                    dataset_id = int(dataset.lastrowid)
                    connection.execute(
                        """
                        INSERT INTO statistical_dataset_items (
                            dataset_id, item_data_no, item_name, full_name,
                            display_order, source_batch_id
                        ) VALUES (?, 1, '값', '값', 1, ?)
                        """,
                        (dataset_id, batch_id),
                    )
                    for period, value, value_batch_id in (
                        ("202300", "10", batch_id),
                        ("202400", "20", batch_id),
                        ("202500", "30", delta_batch_id),
                    ):
                        connection.execute(
                            """
                            INSERT INTO statistical_values (
                                dataset_id, data_cycle, period, data_division,
                                item_data_no, class_data_no, data_value, source_batch_id
                            ) VALUES (?, 'YY', ?, 'OD', 1, -1, ?, ?)
                            """,
                            (dataset_id, period, value, value_batch_id),
                        )
                    connection.execute(
                        """
                        INSERT INTO yearbook_table_recipes (
                            table_code, revision, effective_from_year,
                            source_dataset_id, materializer, config_json,
                            status, source_report_id, source_table_id
                        ) VALUES ('9-9-9', 1, 2025, ?, 'period_rows', ?,
                                  'approved', ?, ?)
                        """,
                        (
                            dataset_id,
                            json.dumps({"value_authority": "source_ledger"}),
                            report_id,
                            table_id,
                        ),
                    )
                    new_dataset = connection.execute(
                        """
                        INSERT INTO statistical_datasets (
                            source_key, external_id, title, introduced_batch_id
                        ) VALUES ('m-new', 'M-NEW', '새 통계', ?)
                        """,
                        (delta_batch_id,),
                    )
                    new_dataset_id = int(new_dataset.lastrowid)
                    connection.execute(
                        """
                        INSERT INTO statistical_dataset_items (
                            dataset_id, item_data_no, item_name, full_name,
                            display_order, source_batch_id
                        ) VALUES (?, 1, '신규 값', '신규 값', 1, ?)
                        """,
                        (new_dataset_id, delta_batch_id),
                    )
                    connection.execute(
                        """
                        INSERT INTO statistical_values (
                            dataset_id, data_cycle, period, data_division,
                            item_data_no, class_data_no, data_value, source_batch_id
                        ) VALUES (?, 'YY', '202500', 'OD', 1, -1, '99', ?)
                        """,
                        (new_dataset_id, delta_batch_id),
                    )

            generated = LedgerYearbookService(db_path).generate(
                base_report_id=report_id,
                target_year=2026,
                source_batch_id=delta_batch_id,
                mode="append_year",
                title="직접 입력한 2026 연보",
            )
            repeated = LedgerYearbookService(db_path).generate(
                base_report_id=report_id,
                target_year=2026,
                source_batch_id=delta_batch_id,
                mode="append_year",
                title="직접 입력한 2026 연보",
            )
            self.assertNotEqual(generated.report_id, repeated.report_id)
            self.assertNotEqual(generated.source_snapshot_id, repeated.source_snapshot_id)
            with connect(db_path) as connection:
                report_row = connection.execute(
                    "SELECT year, title, origin_kind, base_report_id FROM annual_reports WHERE id = ?",
                    (generated.report_id,),
                ).fetchone()
                cells = connection.execute(
                    """
                    SELECT c.row_index, c.col_index, c.text_value
                    FROM stat_table_cells c
                    JOIN stat_tables t ON t.id = c.table_id
                    WHERE t.report_id = ? AND t.code = '9-9-9'
                    ORDER BY c.row_index, c.col_index
                    """,
                    (generated.report_id,),
                ).fetchall()
                preview = connection.execute(
                    """
                    SELECT t.code, t.title, s.generation_status
                    FROM stat_tables t
                    JOIN generated_report_table_status s ON s.table_id = t.id
                    WHERE t.report_id = ? AND t.code = '신규-M-NEW'
                    """,
                    (generated.report_id,),
                ).fetchone()
            values = {
                (int(row["row_index"]), int(row["col_index"])): str(row["text_value"])
                for row in cells
            }
            self.assertEqual(int(report_row["year"]), 2026)
            self.assertEqual(report_row["title"], "직접 입력한 2026 연보")
            self.assertEqual(report_row["origin_kind"], "ledger_generated")
            self.assertEqual(int(report_row["base_report_id"]), report_id)
            self.assertEqual(values[(1, 0)], "2024")
            self.assertEqual(values[(2, 0)], "2025")
            self.assertEqual(values[(2, 1)], "30")
            self.assertIsNotNone(preview)
            self.assertEqual(preview["title"], "새 통계")
            self.assertEqual(preview["generation_status"], "new_table")

            with connect(db_path) as connection:
                snapshot = connection.execute(
                    "SELECT id, parent_snapshot_id FROM source_data_snapshots WHERE report_id = ?",
                    (generated.report_id,),
                ).fetchone()
            self.assertIsNotNone(snapshot)
            assert snapshot is not None
            child_snapshot_id = int(snapshot["id"])
            parent_snapshot_id = int(snapshot["parent_snapshot_id"])

            deleted = DatabaseReportService(db_path).delete_report(generated.report_id)
            self.assertIsNotNone(deleted)
            with connect(db_path) as connection:
                child_count = int(
                    connection.execute(
                        "SELECT COUNT(*) AS count FROM source_data_snapshots WHERE id = ?",
                        (child_snapshot_id,),
                    ).fetchone()["count"]
                )
                parent_count = int(
                    connection.execute(
                        "SELECT COUNT(*) AS count FROM source_data_snapshots WHERE id = ?",
                        (parent_snapshot_id,),
                    ).fetchone()["count"]
                )
            self.assertEqual(child_count, 0)
            self.assertEqual(parent_count, 1)


if __name__ == "__main__":
    unittest.main()
