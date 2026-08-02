from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from app.db.connection import connect
from app.db.schema import init_db
from app.services.ledger_yearbook_service import LedgerYearbookService


class LedgerYearbookServiceTest(unittest.TestCase):
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
                    for period, value in (("202300", "10"), ("202400", "20"), ("202500", "30")):
                        connection.execute(
                            """
                            INSERT INTO statistical_values (
                                dataset_id, data_cycle, period, data_division,
                                item_data_no, class_data_no, data_value, source_batch_id
                            ) VALUES (?, 'YY', ?, 'OD', 1, -1, ?, ?)
                            """,
                            (dataset_id, period, value, batch_id),
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
                        (batch_id,),
                    )
                    new_dataset_id = int(new_dataset.lastrowid)
                    connection.execute(
                        """
                        INSERT INTO statistical_dataset_items (
                            dataset_id, item_data_no, item_name, full_name,
                            display_order, source_batch_id
                        ) VALUES (?, 1, '신규 값', '신규 값', 1, ?)
                        """,
                        (new_dataset_id, batch_id),
                    )
                    connection.execute(
                        """
                        INSERT INTO statistical_values (
                            dataset_id, data_cycle, period, data_division,
                            item_data_no, class_data_no, data_value, source_batch_id
                        ) VALUES (?, 'YY', '202500', 'OD', 1, -1, '99', ?)
                        """,
                        (new_dataset_id, batch_id),
                    )

            generated = LedgerYearbookService(db_path).generate(
                base_report_id=report_id,
                target_year=2026,
                source_batch_id=batch_id,
                mode="append_year",
                title="직접 입력한 2026 연보",
            )
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


if __name__ == "__main__":
    unittest.main()
