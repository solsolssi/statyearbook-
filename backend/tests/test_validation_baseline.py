from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import unittest

from app.db.connection import DB_PATH
from app.services.database_report_service import DatabaseReportService


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "validation_baseline.json"


class ValidationBaselineTest(unittest.TestCase):
    """Guard the reviewed 2025/2026 behavior while internals are refactored."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.service = DatabaseReportService(DB_PATH)
        cls.reports_by_year = {
            str(report["year"]): report for report in cls.service.list_reports()
        }

    def test_snapshot_has_representative_2025_and_2026_tables(self) -> None:
        self.assertEqual(set(self.snapshot["reports"]), {"2025", "2026"})
        for report in self.snapshot["reports"].values():
            self.assertEqual(
                set(report["tables"]),
                {"3-2-1-2", "4-1-8-3", "5-1-1-2", "7-1-8-1"},
            )

    def test_snapshot_records_counts_failure_locations_and_highlights(self) -> None:
        for year, report in self.snapshot["reports"].items():
            for code, table in report["tables"].items():
                with self.subTest(year=year, code=code):
                    self.assertGreater(sum(table["counts"].values()), 0)
                    sample = table["sample"]
                    count_key = next(
                        key
                        for key in table["counts"]
                        if key.endswith(f"|{sample['status']}")
                    )
                    self.assertGreater(table["counts"][count_key], 0)
                    self.assertIsInstance(sample["row_index"], int)
                    self.assertIsInstance(sample["col_index"], int)
                    highlights = sample.get(
                        "highlight_cells",
                        sample.get("highlight_prefix", []),
                    )
                    self.assertGreater(len(highlights), 0)
                    self.assertEqual(highlights[0][2], "target")
                    for row_index, col_index, role in highlights:
                        self.assertGreaterEqual(row_index, 0)
                        self.assertGreaterEqual(col_index, 0)
                        self.assertIn(role, {"target", "related", "header"})

    def test_current_local_reports_match_reviewed_snapshot(self) -> None:
        missing_years = set(self.snapshot["reports"]) - set(self.reports_by_year)
        if missing_years:
            self.skipTest(
                "로컬 기준선 DB가 없어 snapshot 구조 검사만 수행합니다: "
                + ", ".join(sorted(missing_years))
            )

        for year, report_snapshot in self.snapshot["reports"].items():
            report = self.reports_by_year[year]
            self.assertEqual(report["title"], report_snapshot["title"])
            for code, table_snapshot in report_snapshot["tables"].items():
                with self.subTest(year=year, code=code):
                    table = self.service.get_table(f"group-{code}", report["id"])
                    self.assertIsNotNone(table)
                    assert table is not None
                    counts = Counter(
                        f"{check.type}|{check.status}" for check in table.checks
                    )
                    self.assertEqual(dict(counts), table_snapshot["counts"])
                    self.assert_sample_matches(table.checks, table_snapshot["sample"])

    def assert_sample_matches(self, checks, expected: dict) -> None:
        check = next(
            item
            for item in checks
            if item.rule_id == expected["rule_id"]
            and item.status == expected["status"]
            and item.row_index == expected["row_index"]
            and item.col_index == expected["col_index"]
        )
        actual_cells = [
            [cell.row_index, cell.col_index, cell.role]
            for cell in check.highlight_cells
        ]
        if "highlight_cells" in expected:
            self.assertEqual(actual_cells, expected["highlight_cells"])
        else:
            self.assertEqual(
                actual_cells[: len(expected["highlight_prefix"])],
                expected["highlight_prefix"],
            )


if __name__ == "__main__":
    unittest.main()
