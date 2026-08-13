from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db.connection import DatabaseConnection, connect
from app.db.schema import init_db
from app.services.yearbook_reproduction_build_service import (
    YearbookReproductionBuildService,
)
from app.services.database_report_service import DatabaseReportService, TEST_REPORT_ID
from app.services.confirmed_source_mapping_service import (
    ConfirmedSourceMapping,
    ConfirmedSourceMappingService,
)
from app.services.yearbook_reproduction_service import YearbookReproductionService


class YearbookReproductionServiceTest(unittest.TestCase):
    def test_overview_hides_ledger_generated_reports_from_baseline_options(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = insert_report(connection)
                    insert_report(
                        connection,
                        title="증분업로드",
                        file_hash="ledger-generated",
                        origin_kind="ledger_generated",
                    )
                    insert_period_table(connection, report_id)
                    insert_period_dataset(connection)

            overview = YearbookReproductionService(db_path).overview(report_id=report_id)

            self.assertEqual(
                [report.title for report in overview.available_reports],
                ["2025 테스트 연보"],
            )

    def test_user_confirmed_source_mapping_overrides_title_inference(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = insert_report(connection)
                    insert_period_table(connection, report_id)
                    insert_period_dataset(connection)

            applied = ConfirmedSourceMappingService(
                db_path,
                mappings=(
                    ConfirmedSourceMapping(
                        "1-1",
                        ("M-PERIOD",),
                        materializer="period_rows",
                        instructions="테스트에서 사용자가 확정",
                    ),
                ),
            ).synchronize()

            self.assertEqual(applied, 1)
            table = YearbookReproductionService(db_path).overview(
                report_id=report_id
            ).tables[0]
            self.assertEqual(table.mapping_status, "mapped")
            self.assertEqual(table.match_method, "user_confirmed")
            self.assertEqual(table.recipe_status, "approved")
            self.assertEqual(table.source_external_id, "M-PERIOD")
            with connect(db_path) as connection:
                recipe = connection.execute(
                    """
                    SELECT status, approved_by, config_json
                    FROM yearbook_table_recipes
                    WHERE table_code = '1-1'
                    ORDER BY revision DESC
                    LIMIT 1
                    """
                ).fetchone()
            assert recipe is not None
            self.assertEqual(str(recipe["status"]), "approved")
            self.assertEqual(str(recipe["approved_by"]), "yearbook_owner")
            config = json.loads(str(recipe["config_json"]))
            self.assertEqual(config["mapping_authority"], "user_confirmed")
            self.assertEqual(config["source_bindings"][0]["first_period"], "202300")
            self.assertEqual(config["source_bindings"][0]["last_period"], "202400")

    def test_stored_source_id_connects_increment_when_title_changes(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = insert_report(connection)
                    insert_table_with_title(
                        connection,
                        report_id,
                        code="1-9",
                        title="기준 연보의 옛 표 이름",
                        order=1,
                    )
                    dataset_id = insert_dataset(connection, "M-RENAMED", "증분에서 바뀐 표 이름")
                    batch_id = insert_batch(connection, "renamed")
                    insert_item(connection, dataset_id, batch_id, 10001, "합계")
                    insert_value(connection, dataset_id, batch_id, "202400", 10001, 1, "77")
                    connection.execute(
                        """
                        INSERT INTO yearbook_table_recipes (
                            table_code, revision, effective_from_year,
                            source_dataset_id, materializer, config_json,
                            status, source_report_id
                        ) VALUES (
                            '1-9', 1, 2025, ?, 'current_period_rows',
                            '{"value_authority": "source_ledger"}',
                            'draft', ?
                        )
                        """,
                        (dataset_id, report_id),
                    )

            table = YearbookReproductionService(db_path).overview(
                report_id=report_id
            ).tables[0]

            self.assertEqual(table.mapping_status, "mapped")
            self.assertEqual(table.match_method, "source_external_id")
            self.assertEqual(table.source_external_id, "M-RENAMED")
            self.assertIn("원장 번호", table.reason)

    def test_analyzes_mapping_period_window_and_keeps_report_immutable(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = insert_report(connection)
                    insert_period_table(connection, report_id)
                    insert_ambiguous_table(connection, report_id)
                    insert_unmapped_table(connection, report_id)
                    insert_period_dataset(connection)
                    insert_ambiguous_datasets(connection)

            service = YearbookReproductionService(db_path)
            overview = service.overview(report_id=report_id)

            self.assertEqual(overview.report_year, 2025)
            self.assertEqual(overview.target_data_period, "2024")
            self.assertEqual(overview.summary.total_tables, 3)
            self.assertEqual(overview.summary.mapped_tables, 2)
            self.assertEqual(overview.summary.unmapped_tables, 1)
            self.assertEqual(overview.summary.basic_recipe_candidates, 2)
            period_table = overview.tables[0]
            self.assertEqual(period_table.mapping_status, "mapped")
            self.assertEqual(period_table.materializer, "period_rows")
            self.assertEqual(period_table.period_rule.mode, "latest_n")
            self.assertEqual(period_table.period_rule.count, 2)
            self.assertEqual(period_table.period_rule.first_period, "2023")
            self.assertEqual(period_table.period_rule.last_period, "2024")
            ambiguous = overview.tables[1]
            self.assertEqual(ambiguous.mapping_status, "mapped")
            self.assertEqual(ambiguous.source_external_id, "M-CORRECT")
            self.assertIn("값 일치율", ambiguous.reason)

            bootstrap = service.bootstrap_draft_recipes(report_id=report_id)
            repeated = service.bootstrap_draft_recipes(report_id=report_id)
            self.assertEqual(bootstrap.inserted, 3)
            self.assertEqual(bootstrap.mapped, 2)
            self.assertEqual(bootstrap.review_required, 1)
            self.assertEqual(repeated.inserted, 0)
            self.assertEqual(repeated.updated, 3)
            self.assertEqual(repeated.skipped, 0)
            build = YearbookReproductionBuildService(db_path).run(report_id=report_id)
            self.assertEqual(build.total_tables, 3)
            self.assertEqual(build.exact_tables, 2)
            self.assertEqual(build.mapping_review_tables, 1)
            rebuilt_overview = service.overview(report_id=report_id)
            self.assertIsNotNone(rebuilt_overview.latest_build)
            self.assertEqual(rebuilt_overview.tables[0].comparison_status, "exact")
            with connect(db_path) as connection:
                with connection:
                    new_source = connection.execute(
                        """
                        SELECT id
                        FROM statistical_datasets
                        WHERE external_id = 'M-PERIOD'
                        """
                    ).fetchone()
                    assert new_source is not None
                    connection.execute(
                        """
                        INSERT INTO yearbook_edition_manifest (
                            edition_year, table_code, lifecycle_status,
                            target_period, source_dataset_id, title,
                            table_order, is_inferred
                        ) VALUES (2025, '9-9', 'new', '2024', ?,
                                  '신규 테스트 통계', 99, 0)
                        """,
                        (int(new_source["id"]),),
                    )
            test_report = DatabaseReportService(db_path).get_overview_for_report(
                TEST_REPORT_ID
            )
            self.assertTrue(test_report.summary.is_test_report)
            self.assertFalse(test_report.summary.validation_available)
            self.assertEqual(test_report.summary.report_id, TEST_REPORT_ID)
            self.assertTrue(
                any(option.kind == "test" for option in test_report.available_reports)
            )
            self.assertTrue(all(not table.checks for table in test_report.tables))
            self.assertEqual(test_report.tables[0].generation_status, "exact")
            self.assertTrue(
                any(
                    table.generation_status == "mapping_review"
                    for table in test_report.tables
                )
            )
            self.assertTrue(
                any(
                    table.generation_status == "new_table"
                    for table in test_report.tables
                )
            )
            with connect(db_path) as connection:
                with connection:
                    connection.execute(
                        """
                        UPDATE yearbook_edition_manifest
                        SET lifecycle_status = 'no_change', is_inferred = 0
                        WHERE edition_year = 2025 AND table_code = '1-1'
                        """
                    )
            YearbookReproductionBuildService(db_path).run(report_id=report_id)
            with connect(db_path) as connection:
                carried = connection.execute(
                    """
                    SELECT result.status
                    FROM yearbook_reproduction_table_results result
                    JOIN yearbook_reproduction_runs run ON run.id = result.run_id
                    JOIN stat_tables table_row
                      ON table_row.id = result.baseline_table_id
                    WHERE run.baseline_report_id = ?
                      AND table_row.code = '1-1'
                    ORDER BY run.id DESC
                    LIMIT 1
                    """,
                    (report_id,),
                ).fetchone()
            assert carried is not None
            self.assertEqual(str(carried["status"]), "carried_forward")

            with connect(db_path) as connection:
                with connection:
                    connection.execute(
                        """
                        UPDATE yearbook_edition_manifest
                        SET lifecycle_status = 'empty', is_inferred = 0
                        WHERE edition_year = 2025 AND table_code = '1-1'
                        """
                    )
            YearbookReproductionBuildService(db_path).run(report_id=report_id)
            test_overview = DatabaseReportService(db_path).get_overview_for_report(
                TEST_REPORT_ID
            )
            empty_summary = next(
                table for table in test_overview.tables if table.code == "1-1"
            )
            empty_table = DatabaseReportService(db_path).get_table(
                empty_summary.id, TEST_REPORT_ID
            )
            assert empty_table is not None
            self.assertEqual(empty_table.generation_status, "empty")
            self.assertEqual(str(empty_table.rows[0]["c0"]), "2023")
            self.assertEqual(empty_table.rows[0]["c1"], "")

            with connect(db_path) as connection:
                report_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM annual_reports"
                ).fetchone()
                table_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM stat_tables"
                ).fetchone()
                recipe_rows = connection.execute(
                    """
                    SELECT table_code, source_dataset_id, materializer, config_json
                    FROM yearbook_table_recipes
                    ORDER BY table_code
                    """
                ).fetchall()
                policy_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM yearbook_table_update_policies"
                ).fetchone()
                manifest_count = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM yearbook_edition_manifest
                    WHERE edition_year = 2025
                    """
                ).fetchone()
            self.assertEqual(int(report_count["count"]), 1)
            self.assertEqual(int(table_count["count"]), 3)
            self.assertEqual(len(recipe_rows), 3)
            assert policy_count is not None
            self.assertEqual(int(policy_count["count"]), 3)
            assert manifest_count is not None
            self.assertEqual(int(manifest_count["count"]), 4)
            config = json.loads(str(recipe_rows[0]["config_json"]))
            self.assertEqual(config["period_selection"]["count"], 2)
            self.assertEqual(config["target_period_offset"], -1)


def insert_report(
    connection: DatabaseConnection,
    *,
    title: str = "2025 테스트 연보",
    file_hash: str = "report-2025",
    origin_kind: str = "uploaded",
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO annual_reports (
            year, title, source_file_name, source_file_path,
            file_hash, imported_at, origin_kind
        ) VALUES (2025, ?, '2025.md', '', ?, '2025-01-01', ?)
        """,
        (title, file_hash, origin_kind),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def insert_period_table(connection: DatabaseConnection, report_id: int) -> None:
    table_id = insert_table(connection, report_id, "1-1", "연도별 테스트", 1)
    insert_cells(
        connection,
        table_id,
        [
            (0, 0, "연도\nYear", 1),
            (0, 1, "합계\nTotal", 1),
            (1, 0, "2023", 0),
            (1, 1, "10", 0),
            (2, 0, "2024", 0),
            (2, 1, "20", 0),
        ],
    )


def insert_ambiguous_table(connection: DatabaseConnection, report_id: int) -> None:
    table_id = insert_table(connection, report_id, "1-2", "중복 통계", 2)
    insert_cells(
        connection,
        table_id,
        [
            (0, 0, "지역", 1),
            (0, 1, "합계", 1),
            (1, 0, "서울", 0),
            (1, 1, "30", 0),
            (2, 0, "부산", 0),
            (2, 1, "40", 0),
        ],
    )


def insert_unmapped_table(connection: DatabaseConnection, report_id: int) -> None:
    table_id = insert_table(connection, report_id, "1-3", "원장에 없는 통계", 3)
    insert_cells(
        connection,
        table_id,
        [
            (0, 0, "구분", 1),
            (0, 1, "값", 1),
            (1, 0, "합계", 0),
            (1, 1, "1", 0),
        ],
    )


def insert_table_with_title(
    connection: DatabaseConnection,
    report_id: int,
    *,
    code: str,
    title: str,
    order: int,
) -> None:
    table_id = insert_table(connection, report_id, code, title, order)
    insert_cells(
        connection,
        table_id,
        [
            (0, 0, "구분", 1),
            (0, 1, "합계", 1),
            (1, 0, "계", 0),
            (1, 1, "77", 0),
        ],
    )


def insert_table(
    connection: DatabaseConnection,
    report_id: int,
    code: str,
    title: str,
    order: int,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO stat_tables (
            report_id, code, title, table_order
        ) VALUES (?, ?, ?, ?)
        """,
        (report_id, code, title, order),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def insert_cells(
    connection: DatabaseConnection,
    table_id: int,
    cells: list[tuple[int, int, str, int]],
) -> None:
    for row_index, col_index, text, is_header in cells:
        connection.execute(
            """
            INSERT INTO stat_table_cells (
                table_id, row_index, col_index, text_value, is_header
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (table_id, row_index, col_index, text, is_header),
        )


def insert_period_dataset(connection: DatabaseConnection) -> None:
    dataset_id = insert_dataset(connection, "M-PERIOD", "연도별 테스트")
    batch_id = insert_batch(connection, "period")
    insert_item(connection, dataset_id, batch_id, 10001, "합계")
    insert_value(connection, dataset_id, batch_id, "202300", 10001, 1, "10")
    insert_value(connection, dataset_id, batch_id, "202400", 10001, 1, "20")


def insert_ambiguous_datasets(connection: DatabaseConnection) -> None:
    batch_id = insert_batch(connection, "ambiguous")
    wrong_id = insert_dataset(connection, "M-WRONG", "중복 통계")
    correct_id = insert_dataset(connection, "M-CORRECT", "중복 통계")
    for dataset_id in (wrong_id, correct_id):
        insert_item(connection, dataset_id, batch_id, 10001, "지역")
        insert_item(connection, dataset_id, batch_id, 10002, "합계")
    insert_value(connection, wrong_id, batch_id, "202400", 10001, 1, "대전")
    insert_value(connection, wrong_id, batch_id, "202400", 10002, 1, "999")
    insert_value(connection, correct_id, batch_id, "202400", 10001, 1, "서울")
    insert_value(connection, correct_id, batch_id, "202400", 10002, 1, "30")
    insert_value(connection, correct_id, batch_id, "202400", 10001, 2, "부산")
    insert_value(connection, correct_id, batch_id, "202400", 10002, 2, "40")


def insert_dataset(connection: DatabaseConnection, external_id: str, title: str) -> int:
    cursor = connection.execute(
        """
        INSERT INTO statistical_datasets (source_key, external_id, title)
        VALUES (?, ?, ?)
        """,
        (external_id, external_id, title),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def insert_batch(connection: DatabaseConnection, suffix: str) -> int:
    cursor = connection.execute(
        """
        INSERT INTO series_import_batches (
            source_file_name, file_hash, import_kind, target_year
        ) VALUES (?, ?, 'relational_full', 2025)
        """,
        (f"{suffix}.xlsx", f"hash-{suffix}"),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def insert_item(
    connection: DatabaseConnection,
    dataset_id: int,
    batch_id: int,
    item_data_no: int,
    name: str,
) -> None:
    connection.execute(
        """
        INSERT INTO statistical_dataset_items (
            dataset_id, item_data_no, item_name, full_name, source_batch_id
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (dataset_id, item_data_no, name, name, batch_id),
    )


def insert_value(
    connection: DatabaseConnection,
    dataset_id: int,
    batch_id: int,
    period: str,
    item_data_no: int,
    class_data_no: int,
    value: str,
) -> None:
    connection.execute(
        """
        INSERT INTO statistical_values (
            dataset_id, data_cycle, period, data_division,
            item_data_no, class_data_no, data_value, source_batch_id
        ) VALUES (?, 'YY', ?, 'OD', ?, ?, ?, ?)
        """,
        (dataset_id, period, item_data_no, class_data_no, value, batch_id),
    )


if __name__ == "__main__":
    unittest.main()
