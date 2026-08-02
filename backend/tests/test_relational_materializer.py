from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db.connection import connect
from app.db.schema import init_db
from app.yearbook_data.relational_materializer import RelationalTableMaterializer
from test_yearbook_reproduction_service import (
    insert_batch,
    insert_cells,
    insert_dataset,
    insert_item,
    insert_period_dataset,
    insert_period_table,
    insert_report,
    insert_table,
    insert_value,
)


class RelationalTableMaterializerTest(unittest.TestCase):
    def test_empty_values_preserves_headers_and_row_labels(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = insert_report(connection)
                    table_id = insert_table(
                        connection,
                        report_id,
                        "1-0",
                        "빈 값 테스트",
                        1,
                    )
                    insert_cells(
                        connection,
                        table_id,
                        [
                            (0, 0, "지역", 1),
                            (0, 1, "합계", 1),
                            (1, 0, "서울", 0),
                            (1, 1, "10", 0),
                        ],
                    )

            result = RelationalTableMaterializer(db_path).materialize(
                table_id=table_id,
                dataset_id=0,
                materializer="empty_values",
                target_year=2024,
            )

            values = {
                (cell.row_index, cell.col_index): cell.generated_value
                for cell in result.cells
            }
            self.assertEqual(values[(0, 1)], "합계")
            self.assertEqual(values[(1, 0)], "서울")
            self.assertEqual(values[(1, 1)], "")

    def test_period_rows_reproduce_the_baseline_without_writing_a_report(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = insert_report(connection)
                    insert_period_table(connection, report_id)
                    insert_period_dataset(connection)
                table = connection.execute(
                    "SELECT id FROM stat_tables WHERE report_id = ?",
                    (report_id,),
                ).fetchone()
                dataset = connection.execute(
                    "SELECT id FROM statistical_datasets WHERE external_id = 'M-PERIOD'"
                ).fetchone()
            assert table is not None
            assert dataset is not None

            result = RelationalTableMaterializer(db_path).materialize(
                table_id=int(table["id"]),
                dataset_id=int(dataset["id"]),
                materializer="period_rows",
                target_year=2024,
            )

            self.assertEqual(result.status, "exact")
            self.assertEqual(result.mismatch_count, 0)
            with connect(db_path) as connection:
                report_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM annual_reports"
                ).fetchone()
            self.assertEqual(int(report_count["count"]), 1)

    def test_marks_changed_ledger_value_as_source_difference(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = insert_report(connection)
                    insert_period_table(connection, report_id)
                    dataset_id = insert_dataset(
                        connection,
                        "M-PERIOD-DIFFERENCE",
                        "연도별 테스트",
                    )
                    batch_id = insert_batch(connection, "period-difference")
                    insert_item(connection, dataset_id, batch_id, 10001, "합계")
                    insert_value(
                        connection,
                        dataset_id,
                        batch_id,
                        "202300",
                        10001,
                        1,
                        "10",
                    )
                    insert_value(
                        connection,
                        dataset_id,
                        batch_id,
                        "202400",
                        10001,
                        1,
                        "21",
                    )
                table = connection.execute(
                    "SELECT id FROM stat_tables WHERE report_id = ?",
                    (report_id,),
                ).fetchone()
            assert table is not None

            result = RelationalTableMaterializer(db_path).materialize(
                table_id=int(table["id"]),
                dataset_id=dataset_id,
                materializer="period_rows",
                target_year=2024,
            )

            self.assertEqual(result.status, "source_difference")
            self.assertEqual(result.mismatch_count, 1)

    def test_current_rows_derive_a_missing_total_from_source_details(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = insert_report(connection)
                    table_id = insert_table(
                        connection,
                        report_id,
                        "1-4",
                        "지역별 테스트",
                        1,
                    )
                    insert_cells(
                        connection,
                        table_id,
                        [
                            (0, 0, "지역", 1),
                            (0, 1, "합계", 1),
                            (1, 0, "합계", 0),
                            (1, 1, "30", 0),
                            (2, 0, "서울", 0),
                            (2, 1, "10", 0),
                            (3, 0, "부산", 0),
                            (3, 1, "20", 0),
                        ],
                    )
                    dataset_id = insert_dataset(
                        connection,
                        "M-CURRENT-TOTAL",
                        "지역별 테스트",
                    )
                    batch_id = insert_batch(connection, "current-total")
                    insert_item(connection, dataset_id, batch_id, 10001, "지역")
                    insert_item(connection, dataset_id, batch_id, 10002, "합계")
                    for class_number, (region, value) in enumerate(
                        (("서울", "10"), ("부산", "20")),
                        start=1,
                    ):
                        insert_value(
                            connection,
                            dataset_id,
                            batch_id,
                            "202400",
                            10001,
                            class_number,
                            region,
                        )
                        insert_value(
                            connection,
                            dataset_id,
                            batch_id,
                            "202400",
                            10002,
                            class_number,
                            value,
                        )

            result = RelationalTableMaterializer(db_path).materialize(
                table_id=table_id,
                dataset_id=dataset_id,
                materializer="current_period_rows",
                target_year=2024,
            )

            self.assertEqual(result.status, "exact")
            self.assertEqual(result.mismatch_count, 0)

    def test_period_columns_map_source_items_to_measurement_rows(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = insert_report(connection)
                    table_id = insert_table(
                        connection,
                        report_id,
                        "1-5",
                        "연도 열 테스트",
                        1,
                    )
                    insert_cells(
                        connection,
                        table_id,
                        [
                            (0, 0, "구분", 1),
                            (0, 1, "2023", 1),
                            (0, 2, "2024", 1),
                            (1, 0, "접수", 0),
                            (1, 1, "10", 0),
                            (1, 2, "20", 0),
                            (2, 0, "처리", 0),
                            (2, 1, "30", 0),
                            (2, 2, "40", 0),
                        ],
                    )
                    dataset_id = insert_dataset(
                        connection,
                        "M-PERIOD-COLUMNS",
                        "연도 열 테스트",
                    )
                    batch_id = insert_batch(connection, "period-columns")
                    insert_item(connection, dataset_id, batch_id, 10001, "접수")
                    insert_item(connection, dataset_id, batch_id, 10002, "처리")
                    for period, received, processed in (
                        ("202300", "10", "30"),
                        ("202400", "20", "40"),
                    ):
                        insert_value(
                            connection,
                            dataset_id,
                            batch_id,
                            period,
                            10001,
                            1,
                            received,
                        )
                        insert_value(
                            connection,
                            dataset_id,
                            batch_id,
                            period,
                            10002,
                            1,
                            processed,
                        )

            result = RelationalTableMaterializer(db_path).materialize(
                table_id=table_id,
                dataset_id=dataset_id,
                materializer="period_columns",
                target_year=2024,
            )

            self.assertEqual(result.status, "exact")
            self.assertEqual(result.mismatch_count, 0)

    def test_full_snapshot_can_preview_added_rows_without_changing_baseline(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = insert_report(connection)
                    table_id = insert_table(
                        connection,
                        report_id,
                        "1-6",
                        "전체 교체 테스트",
                        1,
                    )
                    insert_cells(
                        connection,
                        table_id,
                        [
                            (0, 0, "지역", 1),
                            (0, 1, "합계", 1),
                            (1, 0, "합계", 0),
                            (1, 1, "30", 0),
                            (2, 0, "서울", 0),
                            (2, 1, "10", 0),
                            (3, 0, "부산", 0),
                            (3, 1, "20", 0),
                        ],
                    )
                    dataset_id = insert_dataset(
                        connection,
                        "M-FULL-SNAPSHOT",
                        "전체 교체 테스트",
                    )
                    batch_id = insert_batch(connection, "full-snapshot")
                    insert_item(connection, dataset_id, batch_id, 10001, "지역")
                    insert_item(connection, dataset_id, batch_id, 10002, "합계")
                    for class_number, (region, value) in enumerate(
                        (("서울", "11"), ("부산", "21"), ("인천", "31")),
                        start=1,
                    ):
                        insert_value(
                            connection,
                            dataset_id,
                            batch_id,
                            "202400",
                            10001,
                            class_number,
                            region,
                        )
                        insert_value(
                            connection,
                            dataset_id,
                            batch_id,
                            "202400",
                            10002,
                            class_number,
                            value,
                        )

            result = RelationalTableMaterializer(db_path).materialize(
                table_id=table_id,
                dataset_id=dataset_id,
                materializer="current_period_rows",
                target_year=2024,
                allow_shape_change=True,
            )

            generated = {
                (cell.row_index, cell.col_index): cell.generated_value
                for cell in result.cells
            }
            self.assertEqual(result.status, "source_difference")
            self.assertEqual(generated[(1, 1)], "63")
            self.assertEqual(generated[(4, 0)], "인천")
            self.assertEqual(generated[(4, 1)], "31")


if __name__ == "__main__":
    unittest.main()
