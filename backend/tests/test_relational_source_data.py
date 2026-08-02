from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import Workbook

from app.db.connection import connect
from app.db.schema import init_db
from app.services.source_statistics_service import SourceStatisticsService
from app.yearbook_data.relational_import import RelationalSourceDataImporter


FULL_VALUE_HEADERS = [
    "seqce_no",
    "statbl_id",
    "dtacycle_cd",
    "wrttime_idtfr_id",
    "dtadvs_cd",
    "itm_datano",
    "cls_datano",
    "dta_val",
    "dta_sval",
    "cmmt_idtfr",
    "cmmt_cont",
    "eng_cmmt_cont",
    "wrtstate_cd",
    "chck_cd",
    "verify_yn",
    "verify_rslt",
    "reg_dtts",
]


def save_workbook(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    workbook.close()


def create_source_files(root: Path, *, changed_value: str = "20") -> dict[str, Path]:
    paths = {
        "full_info": root / "full_info.xlsx",
        "full_items": root / "full_items.xlsx",
        "full_values": root / "full_values.xlsx",
        "delta_info": root / "delta_info.xlsx",
        "delta_items": root / "delta_items.xlsx",
        "delta_values": root / "delta_values.xlsx",
    }
    save_workbook(
        paths["full_info"],
        ["표ID", "표이름", "출처구분", "저장테이블명"],
        [["M1", "지역별 테스트", "행정안전통계", "TB_STTSDATA_01"]],
    )
    item_headers = [
        "표ID",
        "표이름",
        "itmId",
        "레벨",
        "자료번호",
        "항목명",
        "데이터유형",
        "dummy",
        "inputNeedYn",
        "maxLevel",
        "leaf",
        "전체항목명",
        "표시순번",
    ]
    item_rows = [
        ["M1", "지역별 테스트", 1, 1, 10001, "지역", "문자", "N", "N", 1, "Y", "지역", 1],
        ["M1", "지역별 테스트", 2, 1, 10002, "합계", "숫자", "N", "N", 1, "Y", "합계", 2],
    ]
    save_workbook(paths["full_items"], item_headers, item_rows)
    save_workbook(
        paths["full_values"],
        FULL_VALUE_HEADERS,
        [
            [1, "M1", "YY", "202500", "OD", 10001, 1, "서울", "", "", "", "", "PG", "", "Y", "", ""],
            [2, "M1", "YY", "202500", "OD", 10002, 1, "10", "", "", "", "", "PG", "", "Y", "", ""],
            [3, "M1", "YY", "202500", "OD", 10001, 2, "부산", "", "", "", "", "PG", "", "Y", "", ""],
            [4, "M1", "YY", "202500", "OD", 10002, 2, "20", "", "", "", "", "PG", "", "Y", "", ""],
        ],
    )
    save_workbook(
        paths["delta_info"],
        [
            "작성관리번호",
            "표id",
            "표이름",
            "하위디렉토리",
            "디렉토리",
            "입력상태",
            "담당부서",
            "담당자명",
            "입력기간",
            "자료시점",
            "wrttimeIdtfrId",
        ],
        [[100, "M1", "지역별 테스트", "테스트", "통계>테스트", "승인", "통계과", "담당자", "1월", "2025", "202500"]],
    )
    save_workbook(
        paths["delta_items"],
        [header if header != "표ID" else "STATBL_ID" for header in item_headers if header != "표이름"],
        [[value for index, value in enumerate(row) if index != 1] for row in item_rows],
    )
    save_workbook(
        paths["delta_values"],
        ["STATBL_ID", "wrttimeIdtfrId", "자료번호", "데이터행번호", "데이터값", "검증여부"],
        [
            ["M1", "202500", 10001, 1, "서울", "Y"],
            ["M1", "202500", 10002, 1, "10", "Y"],
            ["M1", "202500", 10001, 2, "부산", "Y"],
            ["M1", "202500", 10002, 2, changed_value, "Y"],
        ],
    )
    return paths


class RelationalSourceDataTest(unittest.TestCase):
    def test_full_and_incremental_import_are_separate_from_annual_reports(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "report.sqlite"
            paths = create_source_files(root)
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    connection.execute(
                        """
                        INSERT INTO annual_reports (
                            year, title, source_file_name, source_file_path,
                            file_hash, imported_at
                        ) VALUES (2026, '기존 연보', 'existing.md', '', 'existing', '2026-01-01')
                        """
                    )

            importer = RelationalSourceDataImporter(db_path)
            full = importer.import_full(
                info_path=paths["full_info"],
                item_path=paths["full_items"],
                value_path=paths["full_values"],
            )
            delta = importer.import_delta(
                info_path=paths["delta_info"],
                item_path=paths["delta_items"],
                value_path=paths["delta_values"],
                target_year=2026,
            )

            self.assertEqual(full.inserted_values, 4)
            self.assertEqual(delta.datasets, 1)
            self.assertEqual(delta.unchanged_values, 4)
            with connect(db_path) as connection:
                annual_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM annual_reports"
                ).fetchone()
                value_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM statistical_values"
                ).fetchone()
            self.assertEqual(int(annual_count["count"]), 1)
            self.assertEqual(int(value_count["count"]), 4)

    def test_changed_incremental_value_keeps_a_revision_and_is_visible(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "report.sqlite"
            paths = create_source_files(root)
            importer = RelationalSourceDataImporter(db_path)
            importer.import_full(
                info_path=paths["full_info"],
                item_path=paths["full_items"],
                value_path=paths["full_values"],
            )
            changed_paths = create_source_files(root, changed_value="21")
            changed = importer.import_delta(
                info_path=changed_paths["delta_info"],
                item_path=changed_paths["delta_items"],
                value_path=changed_paths["delta_values"],
                target_year=2027,
            )

            detail = SourceStatisticsService(db_path).detail("M1")
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(changed.updated_values, 1)
            self.assertEqual(detail.rows[1]["item_10002"], "21")
            self.assertEqual(detail.metadata.department, "통계과")
            with connect(db_path) as connection:
                revisions = connection.execute(
                    "SELECT data_value FROM statistical_value_revisions"
                ).fetchall()
            self.assertEqual([row["data_value"] for row in revisions], ["20"])

    def test_overview_and_detail_include_tables_without_values_and_unknown_items(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "report.sqlite"
            paths = create_source_files(root)
            # One value uses an item omitted from the item definition export.
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(FULL_VALUE_HEADERS)
            sheet.append([1, "M1", "YY", "202500", "OD", 10003, 1, "추가값", "", "", "", "", "PG", "", "Y", "", ""])
            workbook.save(paths["full_values"])
            workbook.close()
            save_workbook(
                paths["full_info"],
                ["표ID", "표이름", "출처구분", "저장테이블명"],
                [
                    ["M1", "지역별 테스트", "행정안전통계", "TB_STTSDATA_01"],
                    ["M2", "데이터 없는 통계", "행정안전통계", "TB_STTSDATA_01"],
                ],
            )
            importer = RelationalSourceDataImporter(db_path)
            importer.import_full(
                info_path=paths["full_info"],
                item_path=paths["full_items"],
                value_path=paths["full_values"],
            )

            overview = SourceStatisticsService(db_path).overview()
            detail = SourceStatisticsService(db_path).detail("M1")

            self.assertEqual(overview.summary.total_datasets, 2)
            self.assertEqual(overview.summary.datasets_with_values, 1)
            assert detail is not None
            unknown = next(column for column in detail.columns if column.item_data_no == 10003)
            self.assertEqual(unknown.label, "자료 10003")
            self.assertEqual(detail.rows[0]["item_10003"], "추가값")


if __name__ == "__main__":
    unittest.main()
