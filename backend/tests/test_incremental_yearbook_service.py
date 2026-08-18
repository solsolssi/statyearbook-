from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import Workbook

from app.db.connection import connect
from app.db.schema import init_db
from app.services.database_report_service import DatabaseReportService
from app.services.incremental_yearbook_service import (
    IncrementDataset,
    IncrementItem,
    IncrementValue,
    IncrementalYearbookService,
    analyze_increment_application,
    apply_increment_to_table,
)
from app.yearbook_data.relational_import import (
    DELTA_INFO_COLUMNS,
    DELTA_ITEM_COLUMNS,
    DELTA_VALUE_COLUMNS,
)


class IncrementalYearbookServiceTest(unittest.TestCase):
    def test_creates_a_deletable_draft_without_touching_global_ledger(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report = connection.execute(
                        """
                        INSERT INTO annual_reports (
                            year, title, source_file_name, source_file_path, file_hash, imported_at
                        ) VALUES (2025, '기준 연보', 'base.hwpx', '', 'base', '2025-01-01')
                        """
                    )
                    base_report_id = int(report.lastrowid)
                    table = connection.execute(
                        """
                        INSERT INTO stat_tables (report_id, code, title, source, table_order)
                        VALUES (?, '1-1-2', '정부조직 변천', '원장 번호: STAT-A', 1)
                        """,
                        (base_report_id,),
                    )
                    table_id = int(table.lastrowid)
                    connection.executemany(
                        """
                        INSERT INTO stat_table_cells (table_id, row_index, col_index, text_value, is_header)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        [
                            (table_id, 0, 0, "구분", 1),
                            (table_id, 0, 1, "합계", 1),
                            (table_id, 1, 0, "2025", 0),
                            (table_id, 1, 1, "10", 0),
                        ],
                    )

            info_path = write_xlsx(root / "info.xlsx", DELTA_INFO_COLUMNS, [{
                "표id": "STAT-A", "표이름": "정부조직 변천", "입력상태": "작성중", "작성관리번호": "100", "자료시점": "2025",
            }])
            item_path = write_xlsx(root / "item.xlsx", DELTA_ITEM_COLUMNS, [{
                "STATBL_ID": "STAT-A", "자료번호": 1, "항목명": "합계", "전체항목명": "합계", "표시순번": 1,
            }])
            value_path = write_xlsx(root / "value.xlsx", DELTA_VALUE_COLUMNS, [{
                "STATBL_ID": "STAT-A", "자료번호": 1, "데이터행번호": 1, "데이터값": "42", "wrttimeIdtfrId": "202500",
            }])

            created = IncrementalYearbookService(db_path).create_draft(
                base_report_id=base_report_id,
                target_year=2026,
                title="2026 연보",
                info_path=info_path,
                item_path=item_path,
                value_path=value_path,
            )

            self.assertEqual(created.changed_table_count, 1)
            with connect(db_path) as connection:
                report = connection.execute("SELECT origin_kind FROM annual_reports WHERE id = ?", (created.report_id,)).fetchone()
                value = connection.execute(
                    """
                    SELECT text_value FROM stat_table_cells cell
                    JOIN stat_tables table_row ON table_row.id = cell.table_id
                    WHERE table_row.report_id = ? AND row_index = 1 AND col_index = 1
                    """,
                    (created.report_id,),
                ).fetchone()
                ledger_rows = connection.execute("SELECT COUNT(*) AS count FROM statistical_datasets").fetchone()
            self.assertEqual(str(report["origin_kind"]), "incremental_draft")
            self.assertEqual(str(value["text_value"]), "42")
            self.assertEqual(int(ledger_rows["count"]), 0)
            self.assertIn(created.report_id, [item["id"] for item in DatabaseReportService(db_path).list_reports()])
            DatabaseReportService(db_path).delete_report(created.report_id)

    def test_unmatched_increment_does_not_inflate_visible_table_count(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report = connection.execute(
                        """
                        INSERT INTO annual_reports (
                            year, title, source_file_name, source_file_path, file_hash, imported_at
                        ) VALUES (2025, '기준 연보', 'base.hwpx', '', 'base-unmatched', '2025-01-01')
                        """
                    )
                    base_report_id = int(report.lastrowid)
                    table = connection.execute(
                        """
                        INSERT INTO stat_tables (report_id, code, title, source, table_order)
                        VALUES (?, '1-1-2', '정부조직 변천', '원장 번호: STAT-A', 1)
                        """,
                        (base_report_id,),
                    )
                    table_id = int(table.lastrowid)
                    connection.executemany(
                        """
                        INSERT INTO stat_table_cells (table_id, row_index, col_index, text_value, is_header)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        [
                            (table_id, 0, 0, "구분", 1),
                            (table_id, 0, 1, "합계", 1),
                            (table_id, 1, 0, "2025", 0),
                            (table_id, 1, 1, "10", 0),
                        ],
                    )

            info_path = write_xlsx(root / "info.xlsx", DELTA_INFO_COLUMNS, [
                {"표id": "STAT-A", "표이름": "정부조직 변천", "입력상태": "작성중", "작성관리번호": "100"},
                {"표id": "STAT-NEW", "표이름": "새 증분 통계", "입력상태": "작성중", "작성관리번호": "101"},
            ])
            item_path = write_xlsx(root / "item.xlsx", DELTA_ITEM_COLUMNS, [
                {"STATBL_ID": "STAT-A", "자료번호": 1, "항목명": "합계", "전체항목명": "합계", "표시순번": 1},
                {"STATBL_ID": "STAT-NEW", "자료번호": 1, "항목명": "합계", "전체항목명": "합계", "표시순번": 1},
            ])
            value_path = write_xlsx(root / "value.xlsx", DELTA_VALUE_COLUMNS, [
                {"STATBL_ID": "STAT-A", "자료번호": 1, "데이터행번호": 1, "데이터값": "42", "wrttimeIdtfrId": "202500"},
                {"STATBL_ID": "STAT-NEW", "자료번호": 1, "데이터행번호": 1, "데이터값": "9", "wrttimeIdtfrId": "202500"},
            ])

            created = IncrementalYearbookService(db_path).create_draft(
                base_report_id=base_report_id,
                target_year=2026,
                title="2026 연보",
                info_path=info_path,
                item_path=item_path,
                value_path=value_path,
            )

            with connect(db_path) as connection:
                table_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM stat_tables WHERE report_id = ?",
                    (created.report_id,),
                ).fetchone()
                unmatched = connection.execute(
                    """
                    SELECT source_key
                    FROM report_incremental_table_mappings
                    WHERE report_id = ? AND table_code = '미연결-STAT-NEW'
                    """,
                    (created.report_id,),
                ).fetchone()

            self.assertEqual(created.new_table_count, 1)
            self.assertEqual(int(table_count["count"]), 1)
            self.assertEqual(str(unmatched["source_key"]), "STAT-NEW")

            service = IncrementalYearbookService(db_path)
            service.confirm_draft(created.report_id)
            with connect(db_path) as connection:
                confirmed = connection.execute(
                    "SELECT origin_kind FROM annual_reports WHERE id = ?",
                    (created.report_id,),
                ).fetchone()
                deferred = connection.execute(
                    """SELECT mapping_status FROM report_incremental_table_mappings
                       WHERE report_id = ? AND table_code = '미연결-STAT-NEW'""",
                    (created.report_id,),
                ).fetchone()
            self.assertEqual(str(confirmed["origin_kind"]), "incremental_confirmed")
            self.assertEqual(str(deferred["mapping_status"]), "deferred")

    def test_exact_title_is_a_confirmed_connection_without_a_stored_key(self) -> None:
        """A normal HWPX upload can lack the increment's source key metadata."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report = connection.execute(
                        """
                        INSERT INTO annual_reports (
                            year, title, source_file_name, source_file_path, file_hash, imported_at
                        ) VALUES (2025, '기준 연보', 'base.hwpx', '', 'base-exact-title', '2025-01-01')
                        """
                    )
                    base_report_id = int(report.lastrowid)
                    table = connection.execute(
                        """
                        INSERT INTO stat_tables (report_id, code, title, table_order)
                        VALUES (?, '1-1-2', '정부조직 변천', 1)
                        """,
                        (base_report_id,),
                    )
                    table_id = int(table.lastrowid)
                    connection.executemany(
                        """
                        INSERT INTO stat_table_cells (table_id, row_index, col_index, text_value, is_header)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        [
                            (table_id, 0, 0, "구분", 1),
                            (table_id, 0, 1, "합계", 1),
                            (table_id, 1, 0, "2025", 0),
                            (table_id, 1, 1, "10", 0),
                        ],
                    )

            info_path = write_xlsx(root / "info.xlsx", DELTA_INFO_COLUMNS, [{
                "표id": "STAT-A", "표이름": "정부조직 변천", "입력상태": "작성중", "작성관리번호": "100", "자료시점": "2025",
            }])
            item_path = write_xlsx(root / "item.xlsx", DELTA_ITEM_COLUMNS, [{
                "STATBL_ID": "STAT-A", "자료번호": 1, "항목명": "합계", "전체항목명": "합계", "표시순번": 1,
            }])
            value_path = write_xlsx(root / "value.xlsx", DELTA_VALUE_COLUMNS, [{
                "STATBL_ID": "STAT-A", "자료번호": 1, "데이터행번호": 1, "데이터값": "42", "wrttimeIdtfrId": "202500",
            }])

            created = IncrementalYearbookService(db_path).create_draft(
                base_report_id=base_report_id,
                target_year=2026,
                title="2026 연보",
                info_path=info_path,
                item_path=item_path,
                value_path=value_path,
            )

            self.assertEqual(created.changed_table_count, 1)
            self.assertEqual(created.review_table_count, 0)
            with connect(db_path) as connection:
                with connection:
                    connection.execute(
                        """
                        UPDATE report_incremental_table_mappings
                        SET source_key = '', match_method = '', mapping_status = 'review'
                        WHERE report_id = ? AND table_code = '1-1-2'
                        """,
                        (created.report_id,),
                    )
                    connection.execute(
                        """
                        UPDATE generated_report_table_status
                        SET generation_status = 'mapping_review'
                        WHERE report_id = ?
                        """,
                        (created.report_id,),
                    )
                    connection.execute(
                        """
                        UPDATE stat_table_cells
                        SET text_value = '10'
                        WHERE table_id IN (SELECT id FROM stat_tables WHERE report_id = ?)
                          AND row_index = 1 AND col_index = 1
                        """,
                        (created.report_id,),
                    )
                    connection.execute(
                        "UPDATE report_incremental_uploads SET matcher_version = 0 WHERE report_id = ?",
                        (created.report_id,),
                    )
            self.assertTrue(
                IncrementalYearbookService(db_path).refresh_automatic_mappings(created.report_id)
            )
            with connect(db_path) as connection:
                mapping = connection.execute(
                    """
                    SELECT match_method, mapping_status
                    FROM report_incremental_table_mappings
                    WHERE report_id = ? AND table_code = '1-1-2'
                    """,
                    (created.report_id,),
                ).fetchone()
                status = connection.execute(
                    """
                    SELECT generation_status
                    FROM generated_report_table_status
                    WHERE report_id = ?
                    """,
                    (created.report_id,),
                ).fetchone()
                refreshed_value = connection.execute(
                    """
                    SELECT text_value FROM stat_table_cells
                    WHERE table_id IN (SELECT id FROM stat_tables WHERE report_id = ?)
                      AND row_index = 1 AND col_index = 1
                    """,
                    (created.report_id,),
                ).fetchone()
            self.assertEqual(str(mapping["match_method"]), "exact_title")
            self.assertEqual(str(mapping["mapping_status"]), "mapped")
            self.assertEqual(str(status["generation_status"]), "increment_applied")
            self.assertEqual(str(refreshed_value["text_value"]), "42")

    def test_rejects_upload_when_item_file_does_not_belong_to_info_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report = connection.execute(
                        """
                        INSERT INTO annual_reports (
                            year, title, source_file_name, source_file_path, file_hash, imported_at
                        ) VALUES (2025, '기준 연보', 'base.hwpx', '', 'base-missing-items', '2025-01-01')
                        """
                    )
                    base_report_id = int(report.lastrowid)

            info_path = write_xlsx(root / "info.xlsx", DELTA_INFO_COLUMNS, [{
                "표id": "STAT-A", "표이름": "정부조직 변천", "입력상태": "작성중",
            }])
            item_path = write_xlsx(root / "item.xlsx", DELTA_ITEM_COLUMNS, [{
                "STATBL_ID": "OTHER-STAT", "자료번호": 1, "항목명": "합계", "전체항목명": "합계", "표시순번": 1,
            }])
            value_path = write_xlsx(root / "value.xlsx", DELTA_VALUE_COLUMNS, [{
                "STATBL_ID": "STAT-A", "자료번호": 1, "데이터행번호": 1, "데이터값": "42", "wrttimeIdtfrId": "202500",
            }])

            with self.assertRaisesRegex(ValueError, "표항목 파일"):
                IncrementalYearbookService(db_path).create_draft(
                    base_report_id=base_report_id,
                    target_year=2026,
                    title="2026 연보",
                    info_path=info_path,
                    item_path=item_path,
                    value_path=value_path,
                )

    def test_rejects_value_order_when_increment_omits_item_meanings(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = int(connection.execute(
                        """
                        INSERT INTO annual_reports (
                            year, title, source_file_name, source_file_path, file_hash, imported_at
                        ) VALUES (2025, '기준 연보', 'base.hwpx', '', 'position-only', '2025-01-01')
                        """
                    ).lastrowid)
                    table_id = int(connection.execute(
                        "INSERT INTO stat_tables (report_id, code, title, table_order) VALUES (?, '1-1-2', '정부조직 변천', 1)",
                        (report_id,),
                    ).lastrowid)
                    connection.executemany(
                        """
                        INSERT INTO stat_table_cells (table_id, row_index, col_index, text_value, is_header)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        [
                            (table_id, 0, 0, "연도", 1),
                            (table_id, 0, 1, "부", 1),
                            (table_id, 0, 2, "처", 1),
                            (table_id, 0, 3, "청", 1),
                            (table_id, 0, 4, "위원회", 1),
                            (table_id, 1, 0, "2025", 0),
                            (table_id, 1, 1, "17", 0),
                            (table_id, 1, 2, "3", 0),
                            (table_id, 1, 3, "18", 0),
                            (table_id, 1, 4, "6", 0),
                        ],
                    )
                overlays, _, matched = apply_increment_to_table(
                    connection,
                    table_id,
                    IncrementDataset(
                        key="STAT-A",
                        title="정부조직 변천",
                        values=[
                            IncrementValue(10001, 1, "19"),
                            IncrementValue(10002, 1, "6"),
                            IncrementValue(10003, 1, "18"),
                            IncrementValue(10004, 1, "8"),
                        ],
                    ),
                )

            self.assertFalse(matched)
            self.assertEqual(overlays, {})

    def test_applies_values_only_after_merged_header_paths_and_rows_match(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = int(connection.execute(
                        """INSERT INTO annual_reports
                           (year, title, source_file_name, source_file_path, file_hash, imported_at)
                           VALUES (2025, '기준', 'base.hwpx', '', 'merged', '2025-01-01')"""
                    ).lastrowid)
                    table_id = int(connection.execute(
                        "INSERT INTO stat_tables (report_id, code, title, table_order) VALUES (?, '1-1', '지역 현황', 1)",
                        (report_id,),
                    ).lastrowid)
                    connection.executemany(
                        "INSERT INTO stat_table_cells (table_id,row_index,col_index,text_value,is_header) VALUES (?,?,?,?,?)",
                        [
                            (table_id, 0, 0, "지역", 1),
                            (table_id, 0, 1, "인원", 1),
                            (table_id, 0, 2, "", 1),
                            (table_id, 1, 0, "지역", 1),
                            (table_id, 1, 1, "남", 1),
                            (table_id, 1, 2, "여", 1),
                            (table_id, 2, 0, "서울", 0),
                            (table_id, 2, 1, "1", 0),
                            (table_id, 2, 2, "2", 0),
                            (table_id, 3, 0, "부산", 0),
                            (table_id, 3, 1, "3", 0),
                            (table_id, 3, 2, "4", 0),
                        ],
                    )
                overlays, message, matched = apply_increment_to_table(
                    connection,
                    table_id,
                    IncrementDataset(
                        key="M100",
                        title="지역 현황",
                        items=[
                            IncrementItem(1, "지역", "지역", 1),
                            IncrementItem(2, "남", "인원>남", 2),
                            IncrementItem(3, "여", "인원>여", 3),
                        ],
                        values=[
                            IncrementValue(1, 1, "서울"), IncrementValue(2, 1, "10"), IncrementValue(3, 1, "20"),
                            IncrementValue(1, 2, "부산"), IncrementValue(2, 2, "30"), IncrementValue(3, 2, "40"),
                        ],
                    ),
                )
            self.assertTrue(matched)
            self.assertIn("구조 검증", message)
            self.assertEqual(overlays[(2, 1)], "10")
            self.assertEqual(overlays[(3, 2)], "40")

    def test_manual_mapping_validates_m_key_and_exposes_structured_reason(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    base_report_id = int(connection.execute(
                        """INSERT INTO annual_reports
                           (year,title,source_file_name,source_file_path,file_hash,imported_at)
                           VALUES (2025,'기준','base.hwpx','','manual-base','2025-01-01')"""
                    ).lastrowid)
                    table_id = int(connection.execute(
                        "INSERT INTO stat_tables (report_id,code,title,table_order) VALUES (?,'1-1','합계 현황',1)",
                        (base_report_id,),
                    ).lastrowid)
                    connection.executemany(
                        "INSERT INTO stat_table_cells (table_id,row_index,col_index,text_value,is_header) VALUES (?,?,?,?,?)",
                        [(table_id, 0, 0, "연도", 1), (table_id, 0, 1, "합계", 1),
                         (table_id, 1, 0, "2025", 0), (table_id, 1, 1, "10", 0)],
                    )
            info_path = write_xlsx(root / "info.xlsx", DELTA_INFO_COLUMNS, [
                {"표id": "M100", "표이름": "합계 현황", "입력상태": "작성중", "자료시점": "2025"},
                {"표id": "M200", "표이름": "다른 합계", "입력상태": "작성중", "자료시점": "2025"},
            ])
            item_path = write_xlsx(root / "item.xlsx", DELTA_ITEM_COLUMNS, [
                {"STATBL_ID": "M100", "자료번호": 1, "항목명": "합계", "전체항목명": "합계", "표시순번": 1},
                {"STATBL_ID": "M200", "자료번호": 1, "항목명": "합계", "전체항목명": "합계", "표시순번": 1},
            ])
            value_path = write_xlsx(root / "value.xlsx", DELTA_VALUE_COLUMNS, [
                {"STATBL_ID": "M100", "자료번호": 1, "데이터행번호": 1, "데이터값": "42", "wrttimeIdtfrId": "202500"},
                {"STATBL_ID": "M200", "자료번호": 1, "데이터행번호": 1, "데이터값": "99", "wrttimeIdtfrId": "202500"},
            ])
            service = IncrementalYearbookService(db_path)
            created = service.create_draft(
                base_report_id=base_report_id, target_year=2026, title="초안",
                info_path=info_path, item_path=item_path, value_path=value_path,
            )
            with self.assertRaisesRegex(ValueError, "M으로 시작"):
                service.set_mapping(report_id=created.report_id, table_code="1-1", source_key="100")
            preview = service.preview_mapping(
                report_id=created.report_id, table_code="1-1", source_key="M200"
            )
            self.assertTrue(preview["compatible"])
            self.assertEqual(preview["applied_cell_count"], 1)
            remapped = service.set_mapping(report_id=created.report_id, table_code="1-1", source_key="M200")
            overview = service.list_connections(created.report_id)
            with connect(db_path) as connection:
                value = connection.execute(
                    """SELECT text_value FROM stat_table_cells
                       WHERE table_id IN (SELECT id FROM stat_tables WHERE report_id = ? AND code = '1-1')
                         AND row_index = 1 AND col_index = 1""",
                    (created.report_id,),
                ).fetchone()
            self.assertTrue(remapped["applied"])
            self.assertEqual(str(value["text_value"]), "99")
            self.assertTrue(overview["connections"][0]["confirmed_by_user"])
            self.assertEqual(overview["connections"][0]["reason_code"], "YEAR_ROW_UPDATED")
            created_new = service.create_statistic_from_increment(
                report_id=created.report_id,
                source_key="M100",
                table_code="1-2",
                title="새 합계 현황",
            )
            self.assertEqual(created_new["table_code"], "1-2")
            refreshed_overview = service.list_connections(created.report_id)
            self.assertEqual(refreshed_overview["summary"]["unmatched"], 0)

    def test_rebuilds_changed_merged_headers_from_complete_increment_items(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = int(connection.execute(
                        """INSERT INTO annual_reports
                           (year,title,source_file_name,source_file_path,file_hash,imported_at)
                           VALUES (2025,'기준','base.hwpx','','rebuild','2025-01-01')"""
                    ).lastrowid)
                    table_id = int(connection.execute(
                        "INSERT INTO stat_tables (report_id,code,title,table_order) VALUES (?,'1-2','지역 인원',1)",
                        (report_id,),
                    ).lastrowid)
                    connection.executemany(
                        "INSERT INTO stat_table_cells (table_id,row_index,col_index,text_value,is_header) VALUES (?,?,?,?,?)",
                        [
                            (table_id, 0, 0, "지역", 1), (table_id, 0, 1, "인원", 1),
                            (table_id, 1, 0, "서울", 0), (table_id, 1, 1, "10", 0),
                            (table_id, 2, 0, "부산", 0), (table_id, 2, 1, "20", 0),
                        ],
                    )
                application = analyze_increment_application(
                    connection,
                    table_id,
                    IncrementDataset(
                        key="M300", title="지역 인원",
                        items=[
                            IncrementItem(1, "지역", "지역", 1),
                            IncrementItem(2, "남", "인원>남", 1),
                            IncrementItem(3, "여", "인원>여", 2),
                        ],
                        values=[
                            IncrementValue(1, 1, "서울"), IncrementValue(2, 1, "11"), IncrementValue(3, 1, "12"),
                            IncrementValue(1, 2, "부산"), IncrementValue(2, 2, "21"), IncrementValue(3, 2, "22"),
                        ],
                    ),
                )
            self.assertTrue(application.compatible)
            self.assertEqual(application.reason_code, "STRUCTURE_REBUILT")
            self.assertIsNotNone(application.replacement)
            assert application.replacement is not None
            self.assertEqual(application.replacement.header_count, 2)
            self.assertEqual(application.replacement.column_count, 3)
            values = {(cell.row_index, cell.col_index): cell.value for cell in application.replacement.cells}
            self.assertEqual(values[(0, 1)], "인원")
            self.assertEqual(values[(1, 1)], "남")
            self.assertEqual(values[(2, 2)], "12")

    def test_changed_history_columns_preserve_prior_rows_and_update_target_row(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = int(connection.execute(
                        """INSERT INTO annual_reports
                           (year,title,source_file_name,source_file_path,file_hash,imported_at)
                           VALUES (2025,'기준','base.hwpx','','history','2025-01-01')"""
                    ).lastrowid)
                    table_id = int(connection.execute(
                        "INSERT INTO stat_tables (report_id,code,title,table_order) VALUES (?,'1-3','연도별 현황',1)",
                        (report_id,),
                    ).lastrowid)
                    connection.executemany(
                        "INSERT INTO stat_table_cells (table_id,row_index,col_index,text_value,is_header) VALUES (?,?,?,?,?)",
                        [
                            (table_id, 0, 0, "연도", 1), (table_id, 0, 1, "합계", 1),
                            (table_id, 1, 0, "2024", 0), (table_id, 1, 1, "10", 0),
                            (table_id, 2, 0, "2025", 0), (table_id, 2, 1, "20", 0),
                        ],
                    )
                application = analyze_increment_application(
                    connection,
                    table_id,
                    IncrementDataset(
                        key="M400", title="연도별 현황", reference_time="2026",
                        items=[
                            IncrementItem(1, "합계", "합계", 1),
                            IncrementItem(2, "온라인", "발급>온라인", 2),
                        ],
                        values=[IncrementValue(1, 1, "30"), IncrementValue(2, 1, "7")],
                    ),
                )
            self.assertEqual(application.reason_code, "STRUCTURE_REBUILT")
            assert application.replacement is not None
            self.assertEqual(application.replacement.mode, "year_appended")
            values = {(cell.row_index, cell.col_index): cell.value for cell in application.replacement.cells}
            self.assertEqual(values[(2, 0)], "2025")
            self.assertEqual(values[(2, 1)], "20")
            self.assertEqual(values[(3, 0)], "2026")
            self.assertEqual(values[(3, 1)], "30")
            self.assertEqual(values[(3, 2)], "7")

    def test_time_series_appends_reference_year_without_overwriting_previous_year(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = int(connection.execute(
                        """INSERT INTO annual_reports
                           (year,title,source_file_name,source_file_path,file_hash,imported_at)
                           VALUES (2025,'기준','base.hwpx','','append-year','2025-01-01')"""
                    ).lastrowid)
                    table_id = int(connection.execute(
                        "INSERT INTO stat_tables (report_id,code,title,table_order) VALUES (?,'3-1-3-1','인지도',1)",
                        (report_id,),
                    ).lastrowid)
                    cells = [(table_id, 0, 0, "연도 Year", 1), (table_id, 0, 1, "전체 Total", 1)]
                    for offset, (year, value) in enumerate(
                        [(2020, "90"), (2021, "91"), (2022, "92"), (2023, "93"), (2024, "94")],
                        start=1,
                    ):
                        cells.extend([(table_id, offset, 0, str(year), 0), (table_id, offset, 1, value, 0)])
                    connection.executemany(
                        "INSERT INTO stat_table_cells (table_id,row_index,col_index,text_value,is_header) VALUES (?,?,?,?,?)",
                        cells,
                    )
                application = analyze_increment_application(
                    connection,
                    table_id,
                    IncrementDataset(
                        key="M2025",
                        title="인지도",
                        reference_time="2025",
                        items=[IncrementItem(1, "전체", "전체", 1)],
                        values=[IncrementValue(1, 1, "99")],
                    ),
                )
            self.assertTrue(application.compatible)
            self.assertEqual(application.reason_code, "YEAR_APPENDED")
            assert application.replacement is not None
            values = {(cell.row_index, cell.col_index): cell.value for cell in application.replacement.cells}
            self.assertEqual([values[(row, 0)] for row in range(1, 6)], ["2021", "2022", "2023", "2024", "2025"])
            self.assertEqual(values[(4, 1)], "94")
            self.assertEqual(values[(5, 1)], "99")

    def test_time_column_appends_reference_year_without_dropping_learned_history(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = int(connection.execute(
                        """INSERT INTO annual_reports
                           (year,title,source_file_name,source_file_path,file_hash,imported_at)
                           VALUES (2025,'기준','base.hwpx','','column-year','2025-01-01')"""
                    ).lastrowid)
                    table_id = int(connection.execute(
                        "INSERT INTO stat_tables (report_id,code,title,table_order) VALUES (?,'2-1','지역별 현황',1)",
                        (report_id,),
                    ).lastrowid)
                    connection.executemany(
                        "INSERT INTO stat_table_cells (table_id,row_index,col_index,text_value,is_header) VALUES (?,?,?,?,?)",
                        [
                            (table_id, 0, 0, "지역", 1), (table_id, 0, 1, "2023", 1),
                            (table_id, 0, 2, "2024", 1), (table_id, 1, 0, "서울", 0),
                            (table_id, 1, 1, "10", 0), (table_id, 1, 2, "11", 0),
                            (table_id, 2, 0, "부산", 0), (table_id, 2, 1, "20", 0),
                            (table_id, 2, 2, "21", 0),
                        ],
                    )
                    connection.execute(
                        """INSERT INTO report_incremental_update_recipes
                           (source_key,update_mode,retention_mode,window_size)
                           VALUES ('M-COLUMNS','time_columns','append_history',3)"""
                    )
                application = analyze_increment_application(
                    connection,
                    table_id,
                    IncrementDataset(
                        key="M-COLUMNS", title="지역별 현황", reference_time="2025",
                        items=[
                            IncrementItem(1, "서울", "서울", 1),
                            IncrementItem(2, "부산", "부산", 2),
                        ],
                        values=[IncrementValue(1, 1, "12"), IncrementValue(2, 1, "22")],
                    ),
                )
            self.assertTrue(application.compatible)
            self.assertEqual(application.reason_code, "YEAR_COLUMN_APPENDED")
            assert application.replacement is not None
            values = {(cell.row_index, cell.col_index): cell.value for cell in application.replacement.cells}
            self.assertEqual(application.replacement.column_count, 4)
            self.assertEqual(values[(0, 3)], "2025")
            self.assertEqual(values[(1, 3)], "12")
            self.assertEqual(values[(2, 3)], "22")

    def test_reference_audit_quarantines_a_false_positive_connection(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    draft_id = int(connection.execute(
                        """INSERT INTO annual_reports
                           (year,title,source_file_name,source_file_path,file_hash,imported_at,origin_kind)
                           VALUES (2026,'초안','delta.xlsx','','draft-audit','2026-01-01','incremental_draft')"""
                    ).lastrowid)
                    reference_id = int(connection.execute(
                        """INSERT INTO annual_reports
                           (year,title,source_file_name,source_file_path,file_hash,imported_at)
                           VALUES (2026,'완성본','full.hwpx','','reference-audit','2026-01-02')"""
                    ).lastrowid)
                    table_ids = []
                    for report_id, value in ((draft_id, "11"), (reference_id, "12")):
                        table_id = int(connection.execute(
                            "INSERT INTO stat_tables (report_id,code,title,table_order) VALUES (?,'1-1','대조 통계',1)",
                            (report_id,),
                        ).lastrowid)
                        table_ids.append(table_id)
                        connection.executemany(
                            "INSERT INTO stat_table_cells (table_id,row_index,col_index,text_value,is_header) VALUES (?,?,?,?,?)",
                            [(table_id, 0, 0, "연도", 1), (table_id, 0, 1, "합계", 1),
                             (table_id, 1, 0, "2025", 0), (table_id, 1, 1, value, 0)],
                        )
                    connection.execute(
                        """INSERT INTO generated_report_table_status
                           (report_id,table_id,generation_status,generation_message)
                           VALUES (?,?,'increment_applied','자동 반영')""",
                        (draft_id, table_ids[0]),
                    )
                    connection.execute(
                        """INSERT INTO report_incremental_table_mappings
                           (report_id,table_code,source_key,match_method,mapping_status,reason_code)
                           VALUES (?,'1-1','M-AUDIT','exact_title','applied','STRUCTURE_VERIFIED')""",
                        (draft_id,),
                    )
            result = IncrementalYearbookService(db_path).audit_against_reference_report(
                report_id=draft_id,
                reference_report_id=reference_id,
            )
            self.assertEqual(result["passed"], 0)
            self.assertEqual(result["failed"], 1)
            with connect(db_path) as connection:
                status = connection.execute(
                    "SELECT generation_status FROM generated_report_table_status WHERE report_id = ?",
                    (draft_id,),
                ).fetchone()
                mapping = connection.execute(
                    "SELECT mapping_status,reason_code FROM report_incremental_table_mappings WHERE report_id = ?",
                    (draft_id,),
                ).fetchone()
            self.assertEqual(str(status["generation_status"]), "mapping_review")
            self.assertEqual(str(mapping["mapping_status"]), "review")
            self.assertEqual(str(mapping["reason_code"]), "REFERENCE_VALUE_MISMATCH")

    def test_review_table_is_deferred_when_confirmation_is_requested(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report_id = int(connection.execute(
                        """INSERT INTO annual_reports
                           (year,title,source_file_name,source_file_path,file_hash,imported_at,origin_kind)
                           VALUES (2026,'초안','increment.xlsx','','review-gate','2026-01-01','incremental_draft')"""
                    ).lastrowid)
                    table_id = int(connection.execute(
                        "INSERT INTO stat_tables (report_id,code,title,table_order) VALUES (?,'1-1','확인 통계',1)",
                        (report_id,),
                    ).lastrowid)
                    connection.execute(
                        """INSERT INTO generated_report_table_status
                           (report_id,table_id,generation_status,generation_message)
                           VALUES (?,?,'mapping_review','표항목 정보 없음')""",
                        (report_id, table_id),
                    )
                    connection.execute(
                        """INSERT INTO report_incremental_table_mappings
                           (report_id,table_code,source_key,match_method,mapping_status,reason_code)
                           VALUES (?,'1-1','M500','exact_title','review','MISSING_ITEM_METADATA')""",
                        (report_id,),
                    )

            service = IncrementalYearbookService(db_path)
            service.confirm_draft(report_id)
            with connect(db_path) as connection:
                status = connection.execute(
                    "SELECT generation_status FROM generated_report_table_status WHERE report_id = ?",
                    (report_id,),
                ).fetchone()
                mapping = connection.execute(
                    "SELECT mapping_status, confirmed_by_user FROM report_incremental_table_mappings WHERE report_id = ?",
                    (report_id,),
                ).fetchone()
            self.assertEqual(str(status["generation_status"]), "increment_deferred")
            self.assertEqual(str(mapping["mapping_status"]), "deferred")
            self.assertEqual(int(mapping["confirmed_by_user"]), 0)
            confirmed_table = DatabaseReportService(db_path).get_payload_for_report(report_id).tables[0]
            self.assertEqual(confirmed_table.status_label, "검수 전")


def write_xlsx(path: Path, headers: set[str], rows: list[dict[str, object]]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    ordered_headers = sorted(headers)
    sheet.append(ordered_headers)
    for row in rows:
        sheet.append([row.get(header, "") for header in ordered_headers])
    workbook.save(path)
    return path
