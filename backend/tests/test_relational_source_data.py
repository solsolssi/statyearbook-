from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import Workbook

from app.db.connection import connect
from app.db.schema import init_db
from app.services.source_statistics_service import SourceStatisticsService
from app.yearbook_data.relational_import import RelationalSourceDataImporter
from app.yearbook_data.relational_materializer import source_items, source_matrix
from app.yearbook_data.source_snapshots import (
    SourceSnapshotService,
    activate_source_snapshot,
)


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
                    """
                    SELECT revision.data_value
                    FROM statistical_value_revisions revision
                    JOIN statistical_values value
                      ON value.id = revision.statistical_value_id
                    WHERE value.item_data_no = 10002 AND value.class_data_no = 2
                    """
                ).fetchall()
            self.assertEqual([row["data_value"] for row in revisions], ["20"])

    def test_identical_increment_is_the_only_source_of_the_new_period(self) -> None:
        """A future value in the full ledger cannot leak into an old report."""

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
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report = connection.execute(
                        """
                        INSERT INTO annual_reports (
                            year, title, source_file_name, source_file_path,
                            file_hash, imported_at
                        ) VALUES (2025, '기준', 'base.hwpx', '', 'base', '2025-01-01')
                        """
                    )
                    report_id = int(report.lastrowid)

            delta = importer.import_delta(
                info_path=paths["delta_info"],
                item_path=paths["delta_items"],
                value_path=paths["delta_values"],
                target_year=2026,
            )
            snapshot_service = SourceSnapshotService(db_path)
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    base = snapshot_service.ensure_for_report(
                        connection,
                        report_id=report_id,
                    )
                    child = snapshot_service.create_child(
                        connection,
                        base_report_id=report_id,
                        source_batch_id=delta.batch_id,
                        target_year=2025,
                    )
                    dataset_id = int(
                        connection.execute(
                            "SELECT id FROM statistical_datasets WHERE external_id = 'M1'"
                        ).fetchone()["id"]
                    )
                    with activate_source_snapshot(connection, base.id):
                        base_rows = source_matrix(connection, dataset_id, 2025)
                    with activate_source_snapshot(connection, child.id):
                        child_rows = source_matrix(connection, dataset_id, 2025)
                    value_row = connection.execute(
                        """
                        SELECT source_batch_id
                        FROM statistical_values
                        WHERE dataset_id = ? AND period = '202500'
                          AND item_data_no = 10002 AND class_data_no = 2
                        """,
                        (dataset_id,),
                    ).fetchone()

            self.assertEqual(base_rows, [])
            self.assertEqual(child_rows[1][10002].value, "20")
            assert value_row is not None
            self.assertEqual(int(value_row["source_batch_id"]), delta.batch_id)

    def test_deleted_status_in_increment_creates_a_lifecycle_event(self) -> None:
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
            save_workbook(
                paths["delta_info"],
                [
                    "작성관리번호", "표id", "표이름", "하위디렉토리",
                    "디렉토리", "입력상태", "담당부서", "담당자명",
                    "입력기간", "자료시점", "wrttimeIdtfrId",
                ],
                [[100, "M1", "지역별 테스트", "", "", "폐지", "", "", "", "", ""]],
            )
            result = importer.import_delta(
                info_path=paths["delta_info"],
                item_path=paths["delta_items"],
                value_path=paths["delta_values"],
                target_year=2027,
            )
            with connect(db_path) as connection:
                event = connection.execute(
                    """
                    SELECT lifecycle_status
                    FROM statistical_dataset_lifecycle_events
                    WHERE source_batch_id = ?
                    """,
                    (result.batch_id,),
                ).fetchone()
            self.assertIsNotNone(event)
            self.assertEqual(event["lifecycle_status"], "deleted")

    def test_report_source_snapshots_keep_base_and_increment_values_separate(self) -> None:
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
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report = connection.execute(
                        """
                        INSERT INTO annual_reports (
                            year, title, source_file_name, source_file_path,
                            file_hash, imported_at
                        ) VALUES (2026, '기준', 'base.hwpx', '', 'base', '2026-01-01')
                        """
                    )
                    report_id = int(report.lastrowid)

            changed_paths = create_source_files(root, changed_value="21")
            delta = importer.import_delta(
                info_path=changed_paths["delta_info"],
                item_path=changed_paths["delta_items"],
                value_path=changed_paths["delta_values"],
                target_year=2027,
            )
            snapshot_service = SourceSnapshotService(db_path)
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    base_snapshot = snapshot_service.ensure_for_report(
                        connection,
                        report_id=report_id,
                    )
                    child_snapshot = snapshot_service.create_child(
                        connection,
                        base_report_id=report_id,
                        source_batch_id=delta.batch_id,
                        target_year=2026,
                    )
                    dataset_id = int(
                        connection.execute(
                            "SELECT id FROM statistical_datasets WHERE external_id = 'M1'"
                        ).fetchone()["id"]
                    )
                    with activate_source_snapshot(connection, base_snapshot.id):
                        base_rows = source_matrix(connection, dataset_id, 2025)
                    with activate_source_snapshot(connection, child_snapshot.id):
                        child_rows = source_matrix(connection, dataset_id, 2025)

            self.assertEqual(base_rows[1][10002].value, "20")
            self.assertEqual(child_rows[1][10002].value, "21")

    def test_removed_increment_item_is_hidden_only_in_the_child_snapshot(self) -> None:
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
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    report = connection.execute(
                        """
                        INSERT INTO annual_reports (
                            year, title, source_file_name, source_file_path,
                            file_hash, imported_at
                        ) VALUES (2026, '기준', 'base.hwpx', '', 'base', '2026-01-01')
                        """
                    )
                    report_id = int(report.lastrowid)

            save_workbook(
                paths["delta_items"],
                [
                    "STATBL_ID", "itmId", "레벨", "자료번호", "항목명",
                    "데이터유형", "dummy", "inputNeedYn", "maxLevel",
                    "leaf", "전체항목명", "표시순번",
                ],
                [["M1", 1, 1, 10001, "지역", "문자", "N", "N", 1, "Y", "지역", 1]],
            )
            delta = importer.import_delta(
                info_path=paths["delta_info"],
                item_path=paths["delta_items"],
                value_path=paths["delta_values"],
                target_year=2027,
            )
            snapshot_service = SourceSnapshotService(db_path)
            with connect(db_path) as connection:
                init_db(connection)
                with connection:
                    base = snapshot_service.ensure_for_report(
                        connection,
                        report_id=report_id,
                    )
                    child = snapshot_service.create_child(
                        connection,
                        base_report_id=report_id,
                        source_batch_id=delta.batch_id,
                        target_year=2026,
                    )
                    dataset_id = int(
                        connection.execute(
                            "SELECT id FROM statistical_datasets WHERE external_id = 'M1'"
                        ).fetchone()["id"]
                    )
                    with activate_source_snapshot(connection, base.id):
                        base_items = source_items(connection, dataset_id)
                    with activate_source_snapshot(connection, child.id):
                        child_items = source_items(connection, dataset_id)

            self.assertEqual(set(base_items), {10001, 10002})
            self.assertEqual(set(child_items), {10001})

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
