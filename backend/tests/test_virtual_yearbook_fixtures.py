from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from app.db.connection import connect
from app.export.validation_workbooks import export_validation_workbooks
from app.ingest.markdown_importer import parse_markdown, prepare_markdown_import_tables
from app.ingest.repository import ReportImportRepository
from app.services.incremental_yearbook_service import (
    IncrementalYearbookService,
    parse_increment_files,
)
from app.services.validation_execution_service import ValidationExecutionService
from app.services.llm_assistance_service import ReportLLMAssistanceService
from app.validation.profiles import GPTProfileDraftProvider, HeuristicProfileDraftProvider
from app.validation.repository import ValidationRepository


FIXTURES = Path(__file__).resolve().parents[2] / "generated" / "virtual_yearbook_test"


class VirtualYearbookFixtureTests(unittest.TestCase):
    def test_markdown_versions_cover_expected_statistics_and_structures(self) -> None:
        v1 = prepare_markdown_import_tables(
            parse_markdown(FIXTURES / "virtual_yearbook_v1_2027.md")
        )
        v2 = prepare_markdown_import_tables(
            parse_markdown(FIXTURES / "virtual_yearbook_v2_2028.md")
        )

        self.assertEqual(len({table.code.split(" 표", 1)[0] for table in v1}), 20)
        self.assertEqual(len({table.code.split(" 표", 1)[0] for table in v2}), 21)
        self.assertEqual(
            [table.code for table in v1 if table.code.startswith("9-2-5")],
            ["9-2-5 표1", "9-2-5 표2"],
        )
        merged = next(table for table in v1 if table.code == "9-2-4")
        self.assertEqual(merged.header_count, 2)
        self.assertEqual(merged.unit, "건")
        self.assertEqual(merged.base_date, "2027. 12. 31.")
        merged_v2 = next(table for table in v2 if table.code == "9-2-4")
        self.assertEqual(merged_v2.base_date, "2028. 12. 31.")

        new_table = next(table for table in v2 if table.code == "9-5-1")
        self.assertIn("표준합계(c=a+b)", new_table.matrix[0][3])
        self.assertIn("품질지수", new_table.matrix[0][4])

    def test_increment_files_include_success_review_new_and_delete_cases(self) -> None:
        datasets = parse_increment_files(
            FIXTURES / "virtual_increment_2028_table_info.xlsx",
            FIXTURES / "virtual_increment_2028_table_items.xlsx",
            FIXTURES / "virtual_increment_2028_table_values.xlsx",
        )

        self.assertEqual(len(datasets), 10)
        self.assertEqual(len(datasets["M-V-006"].values), 3)
        self.assertEqual(datasets["M-V-013"].values, [])
        self.assertEqual(datasets["M-V-020"].status, "삭제")
        self.assertEqual(datasets["M-V-021"].target_code, "9-5-1")

    def test_increment_draft_applies_certain_keys_and_keeps_ambiguous_cases_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "fixture.sqlite3"
            source = FIXTURES / "virtual_yearbook_v1_2027.md"
            imported = ReportImportRepository(db_path).replace_report(
                source_path=source,
                year=2027,
                title="2027 가상 통계연보 v1",
                tables=prepare_markdown_import_tables(parse_markdown(source)),
            )
            draft = IncrementalYearbookService(db_path).create_draft(
                base_report_id=imported.report_id,
                target_year=2028,
                title="2028 가상 증분 연보",
                info_path=FIXTURES / "virtual_increment_2028_table_info.xlsx",
                item_path=FIXTURES / "virtual_increment_2028_table_items.xlsx",
                value_path=FIXTURES / "virtual_increment_2028_table_values.xlsx",
            )

            with connect(db_path) as connection:
                rows = connection.execute(
                    """
                    SELECT st.code, mapping.source_key, mapping.reason_code,
                           status.generation_status
                    FROM stat_tables st
                    LEFT JOIN report_incremental_table_mappings mapping
                      ON mapping.report_id = st.report_id AND mapping.table_code = st.code
                    LEFT JOIN generated_report_table_status status
                      ON status.report_id = st.report_id AND status.table_id = st.id
                    WHERE st.report_id = ?
                    """,
                    (draft.report_id,),
                ).fetchall()
            by_code = {str(row["code"]): row for row in rows}

            def llm_decision(_workflow: str, payload: dict[str, object]) -> dict[str, object]:
                decisions = []
                connections = {"9-4-1": "M-A-016", "9-4-2": "M-A-017"}
                for item in payload.get("items", []):
                    if not isinstance(item, dict):
                        continue
                    table_code = str(item.get("table_code") or "")
                    source_key = connections.get(table_code)
                    if not source_key:
                        continue
                    decisions.append({
                        "target_key": str(item["target_key"]),
                        "table_code": table_code,
                        "source_key": source_key,
                        "action": "connect",
                        "update_mode": "snapshot",
                        "retention_mode": "replace",
                        "confidence": 0.98,
                        "reason": "담당 부서와 행 라벨이 함께 일치합니다.",
                    })
                return {"decisions": decisions, "notes": "가상 모호 연결 테스트"}

            assistance = ReportLLMAssistanceService(
                db_path,
                decision_provider=llm_decision,
            ).assist_increment(draft.report_id)

        for code in ("9-2-1", "9-2-2", "9-2-3", "9-2-4"):
            self.assertEqual(by_code[code]["generation_status"], "increment_applied")
        self.assertEqual(by_code["9-3-3"]["reason_code"], "NO_TARGET_VALUES")
        self.assertEqual(by_code["9-3-4"]["reason_code"], "HEADER_STRUCTURE_MISMATCH")
        self.assertEqual(by_code["9-4-1"]["reason_code"], "AMBIGUOUS_CANDIDATE")
        self.assertEqual(assistance["applied"], 2)
        self.assertGreaterEqual(draft.new_table_count, 1)

    def test_validation_detects_seeded_errors_and_reuses_only_unchanged_v2_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "validation.sqlite3"
            repository = ReportImportRepository(db_path)
            v1_path = FIXTURES / "virtual_yearbook_v1_2027.md"
            v2_path = FIXTURES / "virtual_yearbook_v2_2028.md"
            v1 = repository.replace_report(
                source_path=v1_path,
                year=2027,
                title="2027 가상 통계연보 v1",
                tables=prepare_markdown_import_tables(parse_markdown(v1_path)),
            )
            v2 = repository.replace_report(
                source_path=v2_path,
                year=2028,
                title="2028 가상 통계연보 v2",
                tables=prepare_markdown_import_tables(parse_markdown(v2_path)),
            )
            service = ValidationExecutionService(db_path)
            first = service.run(
                report_id=v1.report_id,
                selected_rule_keys=["sum", "ratio", "metadata", "outlier"],
                reuse_existing=False,
            )
            with connect(db_path) as connection:
                errors = connection.execute(
                    """
                    SELECT DISTINCT st.code, check_row.check_type
                    FROM validation_checks check_row
                    JOIN stat_tables st ON st.id = check_row.table_id
                    WHERE check_row.run_id = ? AND check_row.status = '오류 의심'
                    """,
                    (first["run_id"],),
                ).fetchall()
            error_pairs = {(str(row["code"]), str(row["check_type"])) for row in errors}
            self.assertIn(("9-1-3", "합계 검수"), error_pairs)
            self.assertIn(("9-1-5", "비율 검수"), error_pairs)
            exported = export_validation_workbooks(
                db_path,
                report_id=v1.report_id,
                run_id=int(first["run_id"]),
                statuses=["오류 의심"],
                output_dir=Path(directory) / "exports",
            )
            self.assertEqual(exported.validation_rows, 2)
            self.assertTrue(exported.highlighted_path.exists())
            self.assertTrue(exported.validation_index_path.exists())

            second = service.run(
                report_id=v2.report_id,
                selected_rule_keys=["sum", "ratio", "metadata", "outlier"],
                reuse_existing=True,
                source_validation_run_id=int(first["run_id"]),
            )

        self.assertGreater(second["reused_table_count"], 5)
        self.assertLess(second["reused_table_count"], 21)

    def test_new_statistic_separates_deterministic_and_llm_profile_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "profile.sqlite3"
            source = FIXTURES / "virtual_yearbook_v2_2028.md"
            imported = ReportImportRepository(db_path).replace_report(
                source_path=source,
                year=2028,
                title="2028 가상 통계연보 v2",
                tables=prepare_markdown_import_tables(parse_markdown(source)),
            )
            table = next(
                table
                for table in ValidationRepository(db_path).load_tables(imported.report_id)
                if table.code == "9-5-1"
            )

            baseline = HeuristicProfileDraftProvider().draft(table)
            self.assertEqual(baseline.status, "needs_review")
            self.assertIn(4, baseline.rules["uncovered_calculation_columns"])
            self.assertTrue(
                any(
                    check.get("type") == "row_arithmetic"
                    and check.get("target_column") == 3
                    for check in baseline.rules["checks"]
                )
            )

            llm_checks = [
                {
                    "id": "profile.9-5-1.standard_total",
                    "type": "row_arithmetic",
                    "label": "c=a+b",
                    "target_column": 3,
                    "terms": [{"column": 1, "op": "+"}, {"column": 2, "op": "+"}],
                    "row_scope": "all_data_rows",
                    "confidence": 0.99,
                },
                {
                    "id": "profile.9-5-1.quality_ratio",
                    "type": "row_ratio",
                    "label": "품질지수=b/a*100",
                    "target_column": 4,
                    "numerator_column": 2,
                    "denominator_column": 1,
                    "multiplier": 100,
                    "tolerance": 0.15,
                    "confidence": 0.96,
                },
            ]
            assisted = GPTProfileDraftProvider(
                review_only=True,
                decision_provider=lambda _body: {
                    "checks_json": json.dumps(llm_checks, ensure_ascii=False),
                    "notes": "행별 일치 근거로 품질지수 산식을 보강했습니다.",
                },
            ).draft(table)

        self.assertEqual(assisted.source, "llm")
        self.assertEqual(assisted.status, "ready")
        self.assertTrue(
            any(
                check.get("type") == "row_ratio"
                and check.get("target_column") == 4
                for check in assisted.rules["checks"]
            )
        )


if __name__ == "__main__":
    unittest.main()
