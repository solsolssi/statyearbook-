from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db.connection import connect
from app.db.schema import init_db
from app.services.llm_assistance_service import ReportLLMAssistanceService


class ReportLLMAssistanceServiceTest(unittest.TestCase):
    def test_import_assistance_applies_only_valid_high_confidence_interpretation(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = int(connection.execute(
                        """INSERT INTO annual_reports
                           (year,title,source_file_name,source_file_path,file_hash,imported_at)
                           VALUES (2027,'2027 연보','2027.hwpx','','llm-import','2027-01-01')"""
                    ).lastrowid)
                    table_id = int(connection.execute(
                        """INSERT INTO stat_tables
                           (report_id,code,title,table_order,parse_warnings_json)
                           VALUES (?,'1-1','새 통계',1,'[""헤더 확인 필요""]')""",
                        (report_id,),
                    ).lastrowid)
                    connection.executemany(
                        """INSERT INTO stat_table_cells
                           (table_id,row_index,col_index,text_value,is_header)
                           VALUES (?,?,?,?,0)""",
                        [
                            (table_id, 0, 0, "구분"), (table_id, 0, 1, "합계"),
                            (table_id, 1, 0, "2026"), (table_id, 1, 1, "10"),
                        ],
                    )

            service = ReportLLMAssistanceService(
                db_path,
                decision_provider=lambda kind, payload: {
                    "decisions": [{
                        "table_id": table_id,
                        "action": "interpret",
                        "header_row_count": 1,
                        "unit": "개",
                        "base_date": "2026. 12. 31.",
                        "confidence": 0.99,
                        "reason": "첫 행은 열 제목이고 다음 행부터 연도 데이터입니다.",
                    }],
                    "notes": "",
                },
            )
            result = service.assist_import(report_id)

            self.assertEqual(result["applied"], 1)
            with connect(db_path) as connection:
                table = connection.execute(
                    "SELECT unit,base_date FROM stat_tables WHERE id = ?", (table_id,)
                ).fetchone()
                headers = connection.execute(
                    "SELECT row_index,is_header FROM stat_table_cells WHERE table_id = ? ORDER BY row_index,col_index",
                    (table_id,),
                ).fetchall()
                decision = connection.execute(
                    "SELECT status FROM report_llm_assistance_decisions WHERE report_id = ?",
                    (report_id,),
                ).fetchone()
            self.assertEqual(str(table["unit"]), "개")
            self.assertEqual(str(table["base_date"]), "2026. 12. 31.")
            self.assertEqual([int(row["is_header"]) for row in headers], [1, 1, 0, 0])
            self.assertEqual(str(decision["status"]), "applied")

    def test_increment_assistance_uses_existing_preview_before_applying(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    base_id = int(connection.execute(
                        """INSERT INTO annual_reports
                           (year,title,source_file_name,source_file_path,file_hash,imported_at)
                           VALUES (2025,'기준','base.hwpx','','llm-base','2025-01-01')"""
                    ).lastrowid)
                    report_id = int(connection.execute(
                        """INSERT INTO annual_reports
                           (year,title,source_file_name,source_file_path,file_hash,imported_at,origin_kind,base_report_id)
                           VALUES (2026,'초안','increment.xlsx','','llm-draft','2026-01-01','incremental_draft',?)""",
                        (base_id,),
                    ).lastrowid)
                    table_id = int(connection.execute(
                        "INSERT INTO stat_tables (report_id,code,title,table_order) VALUES (?,'1-1','연도별 현황',1)",
                        (report_id,),
                    ).lastrowid)
                    connection.executemany(
                        """INSERT INTO stat_table_cells
                           (table_id,row_index,col_index,text_value,is_header)
                           VALUES (?,?,?,?,?)""",
                        [
                            (table_id, 0, 0, "연도", 1), (table_id, 0, 1, "합계", 1),
                            (table_id, 1, 0, "2024", 0), (table_id, 1, 1, "10", 0),
                        ],
                    )
                    dataset = {
                        "M100": {
                            "key": "M100", "title": "연도별 현황", "reference_time": "2025",
                            "items": [{
                                "data_no": 1, "label": "합계", "full_name": "합계", "order": 1,
                                "data_type": "", "level": 0, "item_id": "",
                            }],
                            "values": [{"data_no": 1, "row_no": 1, "value": "20"}],
                        }
                    }
                    connection.execute(
                        """INSERT INTO report_incremental_uploads
                           (report_id,base_report_id,target_year,payload_json,source_hash,matcher_version)
                           VALUES (?,?,?,?,?,5)""",
                        (report_id, base_id, 2026, json.dumps(dataset), "llm-source"),
                    )
                    connection.execute(
                        """INSERT INTO report_incremental_table_mappings
                           (report_id,table_code,source_key,match_method,mapping_status,reason_code,candidates_json)
                           VALUES (?,'1-1','','candidate_review','review','NO_RELIABLE_CANDIDATE',?)""",
                        (report_id, json.dumps([{"source_key": "M100", "score": 0.7}])),
                    )
                    connection.execute(
                        """INSERT INTO report_incremental_table_mappings
                           (report_id,table_code,source_key,match_method,mapping_status,reason_code)
                           VALUES (?,'미연결-M100','M100','new_increment','review','UNMATCHED_NEW_INCREMENT')""",
                        (report_id,),
                    )
                    connection.execute(
                        """INSERT INTO generated_report_table_status
                           (report_id,table_id,generation_status,generation_message)
                           VALUES (?,?,'mapping_review','연결 확인 필요')""",
                        (report_id, table_id),
                    )

            service = ReportLLMAssistanceService(
                db_path,
                decision_provider=lambda kind, payload: {
                    "decisions": [{
                        "target_key": "table:1-1",
                        "table_code": "1-1",
                        "source_key": "M100",
                        "action": "connect",
                        "update_mode": "time_rows",
                        "retention_mode": "rolling_window",
                        "confidence": 0.99,
                        "reason": "제목과 연도 행 구조가 일치합니다.",
                    }],
                    "notes": "",
                },
            )
            result = service.assist_increment(report_id)

            self.assertEqual(result["applied"], 1)
            with connect(db_path) as connection:
                status = connection.execute(
                    "SELECT generation_status FROM generated_report_table_status WHERE report_id = ?",
                    (report_id,),
                ).fetchone()
                values = connection.execute(
                    "SELECT text_value FROM stat_table_cells WHERE table_id = ? ORDER BY row_index,col_index",
                    (table_id,),
                ).fetchall()
                unmatched = connection.execute(
                    "SELECT COUNT(*) AS count FROM report_incremental_table_mappings WHERE report_id = ? AND match_method = 'new_increment'",
                    (report_id,),
                ).fetchone()
                mapping = connection.execute(
                    "SELECT match_method,confirmed_by_user FROM report_incremental_table_mappings WHERE report_id = ? AND table_code = '1-1'",
                    (report_id,),
                ).fetchone()
            self.assertEqual(str(status["generation_status"]), "increment_applied")
            self.assertIn("20", [str(row["text_value"]) for row in values])
            self.assertEqual(int(unmatched["count"]), 0)
            self.assertEqual(str(mapping["match_method"]), "llm_assisted")
            self.assertEqual(int(mapping["confirmed_by_user"]), 0)

    def test_missing_llm_credentials_preserves_deterministic_result(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = int(connection.execute(
                        """INSERT INTO annual_reports
                           (year,title,source_file_name,source_file_path,file_hash,imported_at)
                           VALUES (2027,'연보','a.hwpx','','no-llm','2027-01-01')"""
                    ).lastrowid)
            service = ReportLLMAssistanceService(db_path)
            result = service.assist_import(report_id)
            self.assertEqual(result["candidates"], 0)
            self.assertEqual(result["applied"], 0)

    def test_unresolved_import_assistance_marks_table_for_parse_review(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = int(connection.execute(
                        """INSERT INTO annual_reports
                           (year,title,source_file_name,source_file_path,file_hash,imported_at)
                           VALUES (2027,'2027 연보','2027.hwpx','','llm-import-review','2027-01-01')"""
                    ).lastrowid)
                    table_id = int(connection.execute(
                        """INSERT INTO stat_tables
                           (report_id,code,title,table_order,parse_warnings_json)
                           VALUES (?,'1-2','파싱 확인 표',1,'[""헤더 행을 확정하지 못했습니다.""]')""",
                        (report_id,),
                    ).lastrowid)
                    connection.execute(
                        """INSERT INTO stat_table_cells
                           (table_id,row_index,col_index,text_value,is_header)
                           VALUES (?,?,?,?,0)""",
                        (table_id, 0, 0, '확인 필요 표'),
                    )

            service = ReportLLMAssistanceService(
                db_path,
                decision_provider=lambda _kind, _payload: {
                    "decisions": [{
                        "table_id": table_id,
                        "action": "review",
                        "header_row_count": None,
                        "unit": "",
                        "base_date": "",
                        "confidence": 0.6,
                        "reason": "헤더 범위를 확정할 수 없습니다.",
                    }],
                    "notes": "",
                },
            )
            result = service.assist_import(report_id)

            self.assertEqual(result['proposed'], 1)
            with connect(db_path) as connection:
                status = connection.execute(
                    """SELECT generation_status FROM generated_report_table_status
                       WHERE report_id = ? AND table_id = ?""",
                    (report_id, table_id),
                ).fetchone()
            self.assertEqual(str(status['generation_status']), 'parse_review')

    def test_profile_preflight_keeps_uncertain_profiles_in_review_without_llm(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = int(connection.execute(
                        """INSERT INTO annual_reports
                           (year,title,source_file_name,source_file_path,file_hash,imported_at)
                           VALUES (2027,'2027 연보','2027.md','','profile-preflight','2027-01-01')"""
                    ).lastrowid)
                    table_id = int(connection.execute(
                        """INSERT INTO stat_tables (report_id,code,title,table_order)
                           VALUES (?,'9-5','산식 미확정 표',1)""",
                        (report_id,),
                    ).lastrowid)
                    connection.executemany(
                        """INSERT INTO stat_table_cells
                           (table_id,row_index,col_index,text_value,numeric_value,is_header)
                           VALUES (?,?,?,?,?,?)""",
                        [
                            (table_id, 0, 0, '구분', None, 1),
                            (table_id, 0, 1, 'A', None, 1),
                            (table_id, 0, 2, 'B', None, 1),
                            (table_id, 0, 3, '산식값', None, 1),
                            (table_id, 1, 0, '항목1', None, 0),
                            (table_id, 1, 1, '10', 10, 0),
                            (table_id, 1, 2, '20', 20, 0),
                            (table_id, 1, 3, '42', 42, 0),
                        ],
                    )

            result = ReportLLMAssistanceService(db_path).assist_profile_drafts(report_id)

            self.assertEqual(result['workflow_kind'], 'validation_profile')
            self.assertEqual(result['candidates'], 1)
            self.assertFalse(result['available'])
            with connect(db_path) as connection:
                profile = connection.execute(
                    "SELECT status FROM validation_profiles WHERE table_code = '9-5'"
                ).fetchone()
            self.assertEqual(str(profile['status']), 'needs_review')


if __name__ == "__main__":
    unittest.main()
