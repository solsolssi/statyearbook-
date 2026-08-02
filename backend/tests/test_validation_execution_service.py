from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db.connection import connect
from app.db.schema import init_db
from app.services.validation_execution_service import ValidationExecutionService


class ValidationExecutionServiceTest(unittest.TestCase):
    def test_selected_checks_reuse_only_identical_tables_from_same_year(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    donor_report = insert_report(connection, year=2026, title="검수 기준")
                    target_report = insert_report(connection, year=2026, title="업로드 수정본")
                    donor_same = insert_table(
                        connection,
                        report_id=donor_report,
                        code="1-1",
                        values=("구분", "합계", "계", "3"),
                    )
                    insert_table(
                        connection,
                        report_id=target_report,
                        code="1-1",
                        values=("구분", "합계", "계", "3"),
                    )
                    donor_changed = insert_table(
                        connection,
                        report_id=donor_report,
                        code="1-2",
                        values=("구분", "합계", "계", "4"),
                    )
                    insert_table(
                        connection,
                        report_id=target_report,
                        code="1-2",
                        values=("구분", "합계", "계", "5"),
                    )
                    donor_run = int(
                        connection.execute(
                            """
                            INSERT INTO validation_runs (
                                report_id, rules_version, started_at, completed_at,
                                selected_rules_json
                            ) VALUES (?, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
                            """,
                            (donor_report, json.dumps(["sum", "ratio"])),
                        ).lastrowid
                    )
                    insert_check(
                        connection,
                        run_id=donor_run,
                        table_id=donor_same,
                        check_type="합계 검수",
                    )
                    insert_check(
                        connection,
                        run_id=donor_run,
                        table_id=donor_same,
                        check_type="비율 검수",
                    )
                    insert_check(
                        connection,
                        run_id=donor_run,
                        table_id=donor_changed,
                        check_type="합계 검수",
                    )

            service = ValidationExecutionService(db_path)
            result = service.run(
                report_id=target_report,
                selected_rule_keys=["sum"],
                reuse_existing=True,
            )

            self.assertEqual(result["selected_rule_keys"], ["sum"])
            self.assertEqual(result["reused_report_count"], 1)
            self.assertEqual(result["reused_table_count"], 1)
            with connect(db_path) as connection:
                checks = connection.execute(
                    """
                    SELECT t.code, c.check_type
                    FROM validation_checks c
                    JOIN stat_tables t ON t.id = c.table_id
                    WHERE c.run_id = ?
                    ORDER BY t.code, c.check_type
                    """,
                    (result["run_id"],),
                ).fetchall()
            same_table_types = [
                str(row["check_type"])
                for row in checks
                if str(row["code"]) == "1-1"
            ]
            self.assertEqual(same_table_types, ["합계 검수"])
            self.assertFalse(
                any(
                    str(row["code"]) == "1-2"
                    and str(row["check_type"]) == "비율 검수"
                    for row in checks
                )
            )

            repeated = service.run(
                report_id=target_report,
                selected_rule_keys=["sum"],
                reuse_existing=True,
            )
            self.assertEqual(repeated["run_id"], result["run_id"])


def insert_report(connection, *, year: int, title: str) -> int:  # type: ignore[no-untyped-def]
    return int(
        connection.execute(
            """
            INSERT INTO annual_reports (
                year, title, source_file_name, source_file_path,
                file_hash, imported_at
            ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (year, title, f"{title}.xlsx", f"/tmp/{title}.xlsx", f"hash-{title}"),
        ).lastrowid
    )


def insert_table(  # type: ignore[no-untyped-def]
    connection,
    *,
    report_id: int,
    code: str,
    values: tuple[str, ...],
) -> int:
    table_id = int(
        connection.execute(
            """
            INSERT INTO stat_tables (
                report_id, code, title, section_title, unit, base_date,
                source, note, table_order
            ) VALUES (?, ?, ?, ?, '명', '2025. 12. 31.', '테스트과', '', 1)
            """,
            (report_id, code, f"{code} 테스트", f"{code} 테스트"),
        ).lastrowid
    )
    connection.executemany(
        """
        INSERT INTO stat_table_cells (
            table_id, row_index, col_index, text_value, numeric_value, is_header
        ) VALUES (?, ?, ?, ?, NULL, ?)
        """,
        [
            (table_id, index // 2, index % 2, value, int(index < 2))
            for index, value in enumerate(values)
        ],
    )
    return table_id


def insert_check(  # type: ignore[no-untyped-def]
    connection,
    *,
    run_id: int,
    table_id: int,
    check_type: str,
) -> None:
    connection.execute(
        """
        INSERT INTO validation_checks (
            run_id, table_id, rule_id, check_type, check_label,
            location, current_value, status, severity, detail
        ) VALUES (?, ?, ?, ?, ?, '2행 2열', '3', '정상', 'info', '테스트')
        """,
        (run_id, table_id, f"test.{check_type}", check_type, check_type),
    )


if __name__ == "__main__":
    unittest.main()
