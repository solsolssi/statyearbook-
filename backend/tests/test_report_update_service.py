from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db.connection import connect
from app.db.schema import init_db
from app.services.report_update_service import (
    ReportComparisonService,
    ReportUpdateService,
)
from app.validation.repository import ValidationRepository


class ReportUpdateServiceTest(unittest.TestCase):
    def test_comparison_ignores_format_only_whitespace(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    left_report_id = insert_report(connection, 2026, "left")
                    right_report_id = insert_report(connection, 2026, "right")
                    insert_table(
                        connection,
                        left_report_id,
                        "A",
                        "같은 표",
                        [["구분", "값"], ["취 득 세", "47.3(42.4)"]],
                    )
                    insert_table(
                        connection,
                        right_report_id,
                        "A",
                        "같은 표",
                        [["구 분", "값"], ["취득세", "47.3(42.4)"]],
                    )

            comparison = ReportComparisonService(db_path).compare(
                left_report_id=left_report_id,
                right_report_id=right_report_id,
            )

            self.assertEqual(comparison.matching_table_count, 1)
            self.assertEqual(comparison.changed_table_count, 0)
            self.assertEqual(comparison.changed_cell_count, 0)

    def test_comparison_ignores_note_page_wrapping_only(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    left_report_id = insert_report(connection, 2026, "left-note")
                    right_report_id = insert_report(connection, 2026, "right-note")
                    left_table_id = insert_table(
                        connection,
                        left_report_id,
                        "A",
                        "같은 표",
                        [["항목", "값"], ["계", "1"]],
                    )
                    right_table_id = insert_table(
                        connection,
                        right_report_id,
                        "A",
                        "같은 표",
                        [["항목", "값"], ["계", "1"]],
                    )
                    connection.execute(
                        "UPDATE stat_tables SET note = ? WHERE id = ?",
                        ("#주1) 첫 문장 이어진 문장", left_table_id),
                    )
                    connection.execute(
                        "UPDATE stat_tables SET note = ? WHERE id = ?",
                        ("#주1) 첫 문장\n이어진 문장", right_table_id),
                    )

            comparison = ReportComparisonService(db_path).compare(
                left_report_id=left_report_id,
                right_report_id=right_report_id,
            )

            self.assertEqual(comparison.matching_table_count, 1)
            self.assertEqual(comparison.changed_table_count, 0)

    def test_diff_comparison_and_unchanged_validation_reuse(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    base_report_id = insert_report(connection, 2026, "base")
                    current_report_id = insert_report(connection, 2026, "current")
                    base_a = insert_table(connection, base_report_id, "A", "같은 표", [["항목", "값"], ["계", "1"]])
                    insert_table(connection, current_report_id, "A", "같은 표", [["항목", "값"], ["계", "1"]])
                    insert_table(connection, base_report_id, "B", "변경 표", [["항목", "값"], ["계", "1"]])
                    current_b = insert_table(
                        connection,
                        current_report_id,
                        "B",
                        "변경 표",
                        [["항목", "값"], ["계", "2"]],
                    )
                    insert_table(connection, base_report_id, "D", "삭제 표", [["항목", "값"]])
                    current_c = insert_table(connection, current_report_id, "C", "추가 표", [["항목", "값"]])

            base_run = ValidationRepository(db_path).save_run(
                report_id=base_report_id,
                rules_version="test",
                issues=[],
                checks=[],
            )
            with connect(db_path) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO validation_checks (
                            run_id, table_id, rule_id, check_type, check_label,
                            location, current_value, status, severity, detail
                        ) VALUES (?, ?, 'test.rule', '합계 검수', '테스트',
                                  '2행 2열', '1', '정상', 'info', '통과')
                        """,
                        (base_run, base_a),
                    )

            update = ReportUpdateService(db_path).record_update(
                base_report_id=base_report_id,
                report_id=current_report_id,
            )
            self.assertEqual(update.changed_table_count, 1)
            self.assertEqual(update.unchanged_table_count, 1)
            self.assertEqual(update.added_table_count, 1)
            self.assertEqual(update.deleted_table_count, 1)
            self.assertEqual(set(update.changed_table_ids), {current_b, current_c})

            new_run = ValidationRepository(db_path).save_run(
                report_id=current_report_id,
                rules_version="test",
                issues=[],
                checks=[],
            )
            copied = ReportUpdateService(db_path).reuse_unchanged_validation(
                batch_id=update.batch_id,
                new_run_id=new_run,
            )
            self.assertEqual(copied, 1)

            comparison = ReportComparisonService(db_path).compare(
                left_report_id=base_report_id,
                right_report_id=current_report_id,
            )
            self.assertEqual(comparison.matching_table_count, 1)
            self.assertEqual(comparison.changed_table_count, 1)
            self.assertEqual(comparison.added_table_count, 1)
            self.assertEqual(comparison.deleted_table_count, 1)
            self.assertEqual(comparison.changed_cell_count, 5)


def insert_report(connection, year: int, key: str) -> int:
    cursor = connection.execute(
        """
        INSERT INTO annual_reports (
            year, title, source_file_name, source_file_path, file_hash, imported_at
        ) VALUES (?, ?, ?, '', ?, '2026-01-01')
        """,
        (year, key, f"{key}.md", key),
    )
    return int(cursor.lastrowid)


def insert_table(connection, report_id: int, code: str, title: str, matrix: list[list[str]]) -> int:
    cursor = connection.execute(
        """
        INSERT INTO stat_tables (
            report_id, code, title, table_order
        ) VALUES (?, ?, ?, ?)
        """,
        (report_id, code, title, ord(code[0])),
    )
    table_id = int(cursor.lastrowid)
    for row_index, row in enumerate(matrix):
        for col_index, value in enumerate(row):
            connection.execute(
                """
                INSERT INTO stat_table_cells (
                    table_id, row_index, col_index, text_value, is_header
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (table_id, row_index, col_index, value, int(row_index == 0)),
            )
    return table_id


if __name__ == "__main__":
    unittest.main()
