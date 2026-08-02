from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
import unittest

from app.application.report_queries import ReportQueryService
from app.db.connection import connect
from app.db.schema import init_db
from app.models.report import StatTableSummary
from app.services.database_report_service import DatabaseReportService


class ReportQueryServiceTest(unittest.TestCase):
    def test_read_operations_delegate_to_the_repository_boundary(self) -> None:
        repository = Mock()
        repository.get_overview_for_report.return_value = object()
        repository.get_payload_for_report.return_value = object()
        repository.list_tables.return_value = []
        repository.get_table.return_value = None
        service = ReportQueryService(repository)

        self.assertIs(service.overview(2026), repository.get_overview_for_report.return_value)
        self.assertIs(service.legacy_payload(2025), repository.get_payload_for_report.return_value)
        self.assertEqual(service.list_tables(2026), [])
        self.assertIsNone(service.table_detail("1-1-1-1", 2026))

        repository.get_overview_for_report.assert_called_once_with(2026)
        repository.get_payload_for_report.assert_called_once_with(2025)
        repository.list_tables.assert_called_once_with(2026)
        repository.get_table.assert_called_once_with("1-1-1-1", 2026)

    def test_overview_projection_cannot_contain_source_cells(self) -> None:
        fields = set(StatTableSummary.model_fields)

        self.assertNotIn("rows", fields)
        self.assertNotIn("columns", fields)
        self.assertNotIn("parts", fields)
        self.assertNotIn("metadata", fields)


class ReportDeleteTest(unittest.TestCase):
    def test_delete_report_removes_uploaded_snapshot_data(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                report_id = insert_report(connection, title="삭제 테스트 연보")
                table_id = insert_table(connection, report_id)
                run_id = insert_validation_run(connection, report_id)
                connection.execute(
                    """
                    INSERT INTO validation_checks (
                        run_id, table_id, rule_id, check_type, check_label,
                        location, status, severity, detail
                    ) VALUES (?, ?, 'rule', '합계', '합계', 'A1', '오류 의심', 'error', 'detail')
                    """,
                    (run_id, table_id),
                )
                connection.execute(
                    """
                    INSERT INTO report_processing_jobs (
                        report_id, source_file_name, source_file_path, source_file_hash,
                        source_file_size, source_type, report_year, report_title
                    ) VALUES (?, 'source.xlsx', '/tmp/source.xlsx', 'hash', 1, 'xlsx', 2027, '삭제 테스트 연보')
                    """,
                    (report_id,),
                )

            result = DatabaseReportService(db_path).delete_report(report_id)

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.report_id, report_id)
            self.assertEqual(result.table_count, 1)
            self.assertEqual(result.validation_run_count, 1)
            with connect(db_path) as connection:
                for table_name in (
                    "annual_reports",
                    "stat_tables",
                    "stat_table_cells",
                    "validation_runs",
                    "validation_checks",
                    "report_processing_jobs",
                ):
                    count = connection.execute(
                        f"SELECT COUNT(*) AS count FROM {table_name}"
                    ).fetchone()["count"]
                    self.assertEqual(count, 0, table_name)

    def test_delete_report_blocks_reports_used_as_a_base(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                base_report_id = insert_report(connection, title="기준 연보")
                insert_report(
                    connection,
                    title="파생 연보",
                    file_hash="child-hash",
                    base_report_id=base_report_id,
                )

            with self.assertRaisesRegex(ValueError, "파생 연보를 먼저 삭제"):
                DatabaseReportService(db_path).delete_report(base_report_id)

    def test_delete_report_blocks_hidden_templates(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                report_id = insert_report(
                    connection,
                    title="숨김 템플릿",
                    is_archived=1,
                    is_template=1,
                )

            with self.assertRaisesRegex(ValueError, "템플릿"):
                DatabaseReportService(db_path).delete_report(report_id)


def insert_report(
    connection,
    *,
    title: str,
    file_hash: str = "report-hash",
    is_archived: int = 0,
    is_template: int = 0,
    base_report_id: int | None = None,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO annual_reports (
            year, title, source_file_name, source_file_path, file_hash,
            imported_at, is_archived, is_template, base_report_id
        ) VALUES (2027, ?, 'source.xlsx', '/tmp/source.xlsx', ?, CURRENT_TIMESTAMP, ?, ?, ?)
        """,
        (title, file_hash, is_archived, is_template, base_report_id),
    )
    return int(cursor.lastrowid)


def insert_table(connection, report_id: int) -> int:
    cursor = connection.execute(
        """
        INSERT INTO stat_tables (
            report_id, code, title, title_en, section_title, section_title_en,
            domain, unit, base_date, section_file, table_order, cell_range,
            note, source, extracted_at, raw_context
        ) VALUES (?, '1-1-1', '테스트 표', '', '', '', '', '', '', '', 1, 'A1:B2', '', '', '', '')
        """,
        (report_id,),
    )
    table_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT INTO stat_table_cells (table_id, row_index, col_index, text_value)
        VALUES (?, 0, 0, '구분')
        """,
        (table_id,),
    )
    return table_id


def insert_validation_run(connection, report_id: int) -> int:
    cursor = connection.execute(
        """
        INSERT INTO validation_runs (
            report_id, rules_version, started_at, completed_at, issue_count
        ) VALUES (?, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)
        """,
        (report_id,),
    )
    return int(cursor.lastrowid)


if __name__ == "__main__":
    unittest.main()
