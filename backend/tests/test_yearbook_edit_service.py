from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db.connection import connect
from app.db.schema import init_db
from app.models.yearbook_edits import (
    EditableCellPatch,
    EditableColumnPatch,
    EditableHierarchyPatch,
    EditableMetadata,
    EditableTablePart,
    TableContentUpdateRequest,
)
from app.services.yearbook_edit_service import (
    YearbookEditAuthenticationError,
    YearbookEditService,
)


class YearbookEditServiceTest(unittest.TestCase):
    def test_password_authentication_and_table_update(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            report_id, table_id = create_fixture(db_path)
            service = YearbookEditService(db_path)

            access = service.get_access(report_id)
            self.assertEqual(len(access.statistics), 1)
            self.assertTrue(access.statistics[0].has_password)
            self.assertTrue(access.statistics[0].is_initial_password)

            with self.assertRaisesRegex(YearbookEditAuthenticationError, "올바르지"):
                service.authenticate(
                    report_id=report_id,
                    table_id=f"db-{table_id}",
                    password="1234",
                )

            session = service.authenticate(
                report_id=report_id,
                table_id=f"db-{table_id}",
                password="4567",
            )
            with connect(db_path) as connection:
                connection.execute(
                    "UPDATE yearbook_edit_sessions SET expires_at = '2000-01-01 00:00:00'"
                )

            updated = service.update_table(
                report_id=report_id,
                table_id=f"db-{table_id}",
                access_token=session.access_token,
                payload=TableContentUpdateRequest(
                    code="1-1-2",
                    title="수정된 표",
                    title_en="Edited Table",
                    section_title="수정 장",
                    section_title_en="Edited Section",
                    domain="행정",
                    parts=[
                        EditableTablePart(
                            id=f"db-{table_id}",
                            code="1-1-2",
                            title="수정된 표",
                            title_en="Edited Table",
                            unit="명",
                            header_count=1,
                            metadata=EditableMetadata(
                                base_date="2027. 12. 31.",
                                note="수정 주석",
                                source="원본 출처",
                                source_department="통계과",
                                source_officer="주무관 홍길동",
                                source_extension="044-123-4567",
                                source_reference="행정안전부",
                            ),
                            columns=[
                                EditableColumnPatch(
                                    source_col_indexes=[1],
                                    label="2027년",
                                    label_en="Year 2027",
                                )
                            ],
                            cells=[
                                EditableCellPatch(
                                    row_index=1,
                                    col_index=1,
                                    value="25",
                                )
                            ],
                        )
                    ],
                ),
            )

            self.assertEqual(updated.code, "1-1-2")
            self.assertEqual(updated.title, "수정된 표")
            self.assertEqual(updated.columns[1].label, "2027년")
            self.assertEqual(updated.rows[0]["c1"], 25)
            self.assertEqual(updated.metadata.source_department, "통계과")
            self.assertEqual(updated.metadata.base_date_display, "2027. 12. 31.")
            self.assertEqual(updated.metadata.unit_display, "명")
            self.assertEqual(updated.status_label, "재검수 필요")
            self.assertTrue(updated.validation_stale)
            self.assertEqual(updated.checks, [])

            with connect(db_path) as connection:
                edit_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM yearbook_manual_edits"
                ).fetchone()["count"]
            self.assertEqual(edit_count, 1)

    def test_changing_password_requires_current_password_and_revokes_sessions(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            report_id, table_id = create_fixture(db_path)
            service = YearbookEditService(db_path)
            service.set_password(
                report_id=report_id,
                table_id=f"db-{table_id}",
                new_password="first",
                current_password="4567",
            )
            session = service.authenticate(
                report_id=report_id,
                table_id=f"db-{table_id}",
                password="first",
            )

            with self.assertRaises(YearbookEditAuthenticationError):
                service.set_password(
                    report_id=report_id,
                    table_id=f"db-{table_id}",
                    new_password="second",
                    current_password="wrong",
                )
            service.set_password(
                report_id=report_id,
                table_id=f"db-{table_id}",
                new_password="second",
                current_password="first",
            )
            with connect(db_path) as connection:
                session_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM yearbook_edit_sessions"
                ).fetchone()["count"]
            self.assertEqual(session_count, 0)
            self.assertTrue(session.access_token)

    def test_passwords_are_scoped_to_each_report_and_statistic(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            first_report_id, first_table_id = create_fixture(db_path, file_hash="first-report")
            second_report_id, second_table_id = create_fixture(db_path, file_hash="second-report")
            other_table_id = insert_table(
                db_path,
                first_report_id,
                code="1-1-2",
                title="다른 통계",
                extension="044-205-9999",
            )
            service = YearbookEditService(db_path)
            service.set_password(
                report_id=first_report_id,
                table_id=f"db-{first_table_id}",
                new_password="first-password",
                current_password="4567",
            )
            service.set_password(
                report_id=second_report_id,
                table_id=f"db-{second_table_id}",
                new_password="second-password",
                current_password="4567",
            )

            first_session = service.authenticate(
                report_id=first_report_id,
                table_id=f"db-{first_table_id}",
                password="first-password",
            )
            self.assertTrue(first_session.access_token)
            with self.assertRaises(YearbookEditAuthenticationError):
                service.authenticate(
                    report_id=second_report_id,
                    table_id=f"db-{second_table_id}",
                    password="first-password",
                )
            with self.assertRaisesRegex(
                YearbookEditAuthenticationError,
                "수정 인증이 유효하지",
            ):
                service.update_table(
                    report_id=first_report_id,
                    table_id=f"db-{other_table_id}",
                    access_token=first_session.access_token,
                    payload=TableContentUpdateRequest(
                        code="1-1-2",
                        title="다른 통계",
                        parts=[
                            EditableTablePart(
                                id=f"db-{other_table_id}",
                                code="1-1-2",
                                title="다른 통계",
                                metadata=EditableMetadata(),
                            )
                        ],
                    ),
                )
            self.assertTrue(
                service.authenticate(
                    report_id=first_report_id,
                    table_id=f"db-{other_table_id}",
                    password="9999",
                ).access_token
            )
            with self.assertRaises(YearbookEditAuthenticationError):
                service.authenticate(
                    report_id=first_report_id,
                    table_id=f"db-{other_table_id}",
                    password="first-password",
                )

    def test_statistic_without_phone_metadata_uses_0000_initial_password(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            report_id, _ = create_fixture(db_path)
            table_id = insert_table(
                db_path,
                report_id,
                code="1-1-2",
                title="연락처 없는 통계",
                extension="",
            )
            service = YearbookEditService(db_path)

            self.assertTrue(
                service.authenticate(
                    report_id=report_id,
                    table_id=f"db-{table_id}",
                    password="0000",
                ).access_token
            )
            with self.assertRaises(YearbookEditAuthenticationError):
                service.authenticate(
                    report_id=report_id,
                    table_id=f"db-{table_id}",
                    password="4567",
                )

    def test_section_hierarchy_changes_apply_to_all_matching_tables(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "report.sqlite"
            report_id, table_id = create_fixture(db_path)
            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO stat_tables (
                        report_id, code, title, title_en, section_title,
                        section_title_en, domain, unit, base_date, section_file,
                        table_order, cell_range, note, source, extracted_at, raw_context
                    ) VALUES (?, '1-1-2', '두 번째 표', '', '테스트 장', '', '행정',
                              '건', '2026 기준', 'sheet', 2, 'A1:B2', '', '', CURRENT_TIMESTAMP, '')
                    """,
                    (report_id,),
                )
            service = YearbookEditService(db_path)
            session = service.authenticate(
                report_id=report_id,
                table_id=f"db-{table_id}",
                password="4567",
            )

            service.update_table(
                report_id=report_id,
                table_id=f"db-{table_id}",
                access_token=session.access_token,
                payload=TableContentUpdateRequest(
                    code="1-2-1",
                    title="테스트 표",
                    title_en="Test Table",
                    section_title="바뀐 장",
                    section_title_en="Renamed Section",
                    domain="행정",
                    hierarchy_patches=[
                        EditableHierarchyPatch(
                            kind="section",
                            original_code="1-1",
                            code="1-2",
                            title="바뀐 장",
                            title_en="Renamed Section",
                        )
                    ],
                    parts=[
                        EditableTablePart(
                            id=f"db-{table_id}",
                            code="1-2-1",
                            title="테스트 표",
                            title_en="Test Table",
                            unit="건",
                            header_count=1,
                            metadata=EditableMetadata(base_date="2026 기준"),
                        )
                    ],
                ),
            )

            with connect(db_path) as connection:
                rows = connection.execute(
                    """
                    SELECT code, section_title, section_title_en FROM stat_tables
                    WHERE report_id = ? ORDER BY table_order
                    """,
                    (report_id,),
                ).fetchall()
            self.assertEqual([str(row["code"]) for row in rows], ["1-2-1", "1-2-2"])
            self.assertTrue(all(row["section_title"] == "바뀐 장" for row in rows))
            self.assertTrue(all(row["section_title_en"] == "Renamed Section" for row in rows))


def create_fixture(db_path: Path, *, file_hash: str = "edit-fixture") -> tuple[int, int]:
    with connect(db_path) as connection:
        init_db(connection)
        report_cursor = connection.execute(
            """
            INSERT INTO annual_reports (
                year, title, source_file_name, source_file_path, file_hash, imported_at
            ) VALUES (2027, '테스트 연보', 'source.xlsx', '/tmp/source.xlsx',
                      ?, CURRENT_TIMESTAMP)
            """,
            (file_hash,),
        )
        report_id = int(report_cursor.lastrowid)
        table_cursor = connection.execute(
            """
            INSERT INTO stat_tables (
                report_id, code, title, title_en, section_title, section_title_en,
                domain, unit, base_date, section_file, table_order, cell_range,
                note, source, source_extension, extracted_at, raw_context
            ) VALUES (?, '1-1-1', '테스트 표', 'Test Table', '테스트 장', '',
                      '행정', '건', '2026 기준', 'sheet', 1, 'A1:B2', '', '',
                      '044-123-4567', CURRENT_TIMESTAMP, '')
            """,
            (report_id,),
        )
        table_id = int(table_cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO stat_table_cells (
                table_id, row_index, col_index, text_value, numeric_value, is_header
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (table_id, 0, 0, "구분", None, 1),
                (table_id, 0, 1, "2026", 2026, 1),
                (table_id, 1, 0, "합계", None, 0),
                (table_id, 1, 1, "10", 10, 0),
            ],
        )
        run_cursor = connection.execute(
            """
            INSERT INTO validation_runs (
                report_id, rules_version, started_at, completed_at, issue_count
            ) VALUES (?, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)
            """,
            (report_id,),
        )
        connection.execute(
            """
            INSERT INTO validation_checks (
                run_id, table_id, rule_id, check_type, check_label, location,
                row_index, col_index, current_value, status, severity, detail
            ) VALUES (?, ?, 'rule', '합계', '합계', '합계 / 2026', 1, 1,
                      '10', '정상', 'info', '통과')
            """,
            (int(run_cursor.lastrowid), table_id),
        )
    return report_id, table_id


def insert_table(
    db_path: Path,
    report_id: int,
    *,
    code: str,
    title: str,
    extension: str,
) -> int:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO stat_tables (
                report_id, code, title, title_en, section_title, section_title_en,
                domain, unit, base_date, section_file, table_order, cell_range,
                note, source, source_extension, extracted_at, raw_context
            ) VALUES (?, ?, ?, '', '테스트 장', '', '행정', '건', '2026 기준',
                      'sheet', 2, 'A1:B2', '', '', ?, CURRENT_TIMESTAMP, '')
            """,
            (report_id, code, title, extension),
        )
        return int(cursor.lastrowid)


if __name__ == "__main__":
    unittest.main()
