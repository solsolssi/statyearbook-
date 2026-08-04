from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from app.ingest.hwpx_importer import (
    LogicalTable,
    TablePart,
    cell_text_with_footnote,
    element_text,
    is_data_table,
    is_metadata_text,
    is_note_continuation_text,
    is_title_table,
    normalize_table_sources,
    prepare_hwpx_import_tables,
    parse_title_block,
    remember_title_context,
    resolve_title_section,
    separate_bilingual_lines,
)
from app.services.database_report_service import row_looks_like_header_continuation


class HwpxImporterTest(unittest.TestCase):
    def test_element_text_preserves_paragraphs_and_ignores_memos(self) -> None:
        cell = ET.fromstring(
            """
            <tc>
              <p>
                <run><t>3-1-4</t></run>
                <run>
                  <ctrl>
                    <fieldBegin type="MEMO">
                      <parameters><stringParam>MEMO/internal</stringParam></parameters>
                      <subList><p><run><t>데이터미입력</t></run></p></subList>
                    </fieldBegin>
                  </ctrl>
                </run>
                <run><t>국가정보통신망</t></run>
              </p>
              <p><run><t>E-Government Network</t></run></p>
            </tc>
            """
        )

        self.assertEqual(
            element_text(cell),
            "3-1-4국가정보통신망\nE-Government Network",
        )

    def test_parse_title_block_splits_parent_and_child_bilingual_titles(self) -> None:
        self.assertEqual(
            parse_title_block(
                "2-1-4 혜택알리미\nSubsidies 24\n"
                "2-1-4-1 가입자 수\nNumber of Subscribers"
            ),
            (
                "2-1-4-1",
                "가입자 수",
                "Number of Subscribers",
                "혜택알리미",
                "Subsidies 24",
            ),
        )

    def test_parse_title_block_ignores_range_marker(self) -> None:
        self.assertEqual(
            parse_title_block(
                "7-2-1 지진 발생\nEarthquake Occurrence\n"
                "7-2-1-1~3\n"
                "7-2-1-1 지역별 지진발생\n"
                "Domestic Earthquake Occurrence by Region"
            ),
            (
                "7-2-1-1",
                "지역별 지진발생",
                "Domestic Earthquake Occurrence by Region",
                "지진 발생",
                "Earthquake Occurrence",
            ),
        )

    def test_parse_title_block_supports_numeric_title_without_space(self) -> None:
        self.assertEqual(
            parse_title_block(
                "8-1-1-330년경과 비공개기록물 재분류 "
                "Reclassification of Non-disclosed Archives After 30 Years"
            )[:3],
            (
                "8-1-1-3",
                "30년경과 비공개기록물 재분류",
                "Reclassification of Non-disclosed Archives After 30 Years",
            ),
        )

    def test_parse_title_block_supports_appendix_codes(self) -> None:
        self.assertEqual(
            parse_title_block(
                "부록1 행정안전부 공무원 정원\n"
                "Fixed Number of Civil Servants in MOIS\n"
                "부록 1-1 기관별･직종별 정원\n"
                "Fixed Number of Civil Servants in MOIS by Organizations/Type"
            ),
            (
                "부록 1-1",
                "기관별･직종별 정원",
                "Fixed Number of Civil Servants in MOIS by Organizations/Type",
                "행정안전부 공무원 정원",
                "Fixed Number of Civil Servants in MOIS",
            ),
        )

    def test_bilingual_cell_lines_are_separated_even_without_a_space(self) -> None:
        self.assertEqual(
            separate_bilingual_lines(
                "해양안전심판원(중앙·지방)Maritime Safety Tribunal\n"
                "GPS전파혼신 GPS radio interference"
            ),
            "해양안전심판원(중앙·지방)\nMaritime Safety Tribunal\n"
            "GPS전파혼신\nGPS radio interference",
        )
        self.assertEqual(separate_bilingual_lines("5t or less"), "5t or less")
        self.assertEqual(
            separate_bilingual_lines("90km west-southwest sea area"),
            "90km west-southwest sea area",
        )

    def test_english_placeholder_is_not_part_of_korean_title(self) -> None:
        self.assertEqual(
            parse_title_block("2-1-4-1 가입자 수(영문)")[:3],
            ("2-1-4-1", "가입자 수", ""),
        )

    def test_wide_data_table_is_not_a_title_table(self) -> None:
        matrix = [
            ["구분", "2010", "2011"],
            ["주민소송", "7", "-"],
            ["합계", "7", "-"],
        ]
        self.assertFalse(is_title_table(matrix, "구분 2010 2011 주민소송 7 - 4-1-2"))

    def test_page_continuations_drop_repeated_headers_and_empty_grid_columns(self) -> None:
        table = LogicalTable(
            code="1-1-5",
            title="행정기관 위원회",
            title_en="",
            section_title="",
            section_title_en="",
            section_file="Contents/section1.xml",
            table_order=1,
            parts=[
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[
                        ["구분", "", "", "합계", "행정"],
                        ["2009", "", "", "10", "4"],
                    ],
                    raw_text="",
                ),
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[
                        ["구분", "합계", "행정"],
                        ["2010", "11", "5"],
                    ],
                    raw_text="",
                ),
            ],
        )

        imported = prepare_hwpx_import_tables([table])

        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0].code, "1-1-5")
        self.assertEqual(
            imported[0].matrix,
            [["구분", "합계", "행정"], ["2009", "10", "4"], ["2010", "11", "5"]],
        )
        self.assertEqual(imported[0].header_count, 1)

    def test_authored_bilingual_and_formula_line_boundaries_are_preserved(self) -> None:
        table = LogicalTable(
            code="5-1-1-1",
            title="지방자치단체 예산 총괄",
            title_en="Summary of Local Government Budget",
            section_title="",
            section_title_en="",
            section_file="Contents/section1.xml",
            table_order=1,
            parts=[
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[
                        [
                            "구 분\nClassification",
                            "2026년도\nYear 2026\n(A)",
                            "증 감 (A-B)\nChange",
                        ],
                        ["총규모\nTotal", "3,418,710", "158,561"],
                    ],
                    raw_text="",
                )
            ],
        )

        imported = prepare_hwpx_import_tables([table])

        self.assertEqual(
            imported[0].matrix[0],
            [
                "구 분\nClassification",
                "2026년도\nYear 2026\n(A)",
                "증 감 (A-B)\nChange",
            ],
        )

    def test_wide_row_oriented_text_table_keeps_descriptor_rows_as_data(self) -> None:
        table = LogicalTable(
            code="6-3-3-3 표2",
            title="지역별 재난경보 및 재난예방 방송",
            title_en="Disaster Alert and Disaster Prevention Broadcasting by Region",
            section_title="",
            section_title_en="",
            section_file="Contents/section1.xml",
            table_order=1,
            parts=[
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[
                        [
                            "구분\nClassification",
                            "실제 경보 발령\nActual Alert",
                            "훈련 경보발령\nDrill Alert",
                            "기타(묵념사이렌)\nOthers (Siren to signal silent tribute)",
                            "",
                        ],
                        [
                            "울림사유\nReason for alert",
                            "-",
                            "을지연습\nUlchi Freedom Shield",
                            "4･3 희생자 추념식\nCommemoration ceremony of 4･3 incident",
                            "세월호 참사 기억식\nSewol ferry memorial",
                        ],
                        [
                            "울림횟수\nNumber of alerts",
                            "-",
                            "1회\n(8.20)\n1 time\n(August 20)",
                            "1회\n(4.3)\n1 time\n(Apr. 3)",
                            "1회\n(4.16)\n1 time\n(Apr. 16)",
                        ],
                        [
                            "울림지역\nAlerted area",
                            "-",
                            "전국\nNational",
                            "제주\nJeju",
                            "안산\nAnsan",
                        ],
                    ],
                    raw_text="",
                )
            ],
        )

        imported = prepare_hwpx_import_tables([table])

        self.assertEqual(imported[0].header_count, 1)

    def test_leading_english_number_stays_on_the_english_line(self) -> None:
        table = LogicalTable(
            code="4-1-1-6",
            title="인구 규모별 행정구역",
            title_en="Administrative District Statistics by Population Size",
            section_title="",
            section_title_en="",
            section_file="Contents/section1.xml",
            table_order=1,
            parts=[
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[
                        [
                            "50만 명 이상\n500,000 Persons or more",
                            "30 ~ 50만 명\n300,000 up to 500,000 Persons",
                        ],
                        ["17", "10"],
                    ],
                    raw_text="",
                )
            ],
        )

        imported = prepare_hwpx_import_tables([table])

        self.assertEqual(imported[0].matrix[0][0], "50만 명 이상\n500,000 Persons or more")
        self.assertEqual(
            imported[0].matrix[0][1],
            "30 ~ 50만 명\n300,000 up to 500,000 Persons",
        )

    def test_text_only_first_row_on_next_page_is_data_not_an_extra_header(self) -> None:
        table = LogicalTable(
            code="7-2-10",
            title="재난·안전 정보시스템",
            title_en="",
            section_title="",
            section_title_en="",
            section_file="Contents/section1.xml",
            table_order=1,
            parts=[
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[
                        ["시스템", "소관부서", "주요기능"],
                        ["재난관리시스템", "재난정보통신과", "시설물관리, 이재민 관리, 복구계획"],
                    ],
                    raw_text="",
                ),
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[
                        ["시스템", "소관부서", "주요기능"],
                        ["자연재해 안전도 진단지원시스템", "재난영향분석과", "지역안전지수 관련 정보의 취합‧분석‧공유"],
                    ],
                    raw_text="",
                ),
            ],
        )

        imported = prepare_hwpx_import_tables([table])

        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0].header_count, 1)
        self.assertEqual(len(imported[0].matrix), 3)
        self.assertEqual(imported[0].matrix[2][0], "자연재해 안전도 진단지원시스템")

    def test_incompatible_part_headers_become_grouped_subtables(self) -> None:
        table = LogicalTable(
            code="1-1-1-4",
            title="중앙행정기관 연도별 하부기구",
            title_en="",
            section_title="",
            section_title_en="",
            section_file="Contents/section1.xml",
            table_order=1,
            parts=[
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[["연도", "실", "국"], ["2018", "47", "176"]],
                    raw_text="(2025. 12. 31. 기준)(단위 : 개)",
                ),
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[["연도", "차관", "보조"], ["2019", "41", "54"]],
                    raw_text="",
                ),
            ],
        )

        imported = prepare_hwpx_import_tables([table])

        self.assertEqual([item.code for item in imported], ["1-1-1-4 표1", "1-1-1-4 표2"])
        self.assertEqual(imported[0].matrix[0], ["연도", "실", "국"])
        self.assertEqual(imported[1].matrix[0], ["연도", "차관", "보조"])
        self.assertEqual([(item.unit, item.base_date) for item in imported], [("개", "2025. 12. 31."), ("개", "2025. 12. 31.")])

    def test_outside_metadata_context_supplies_base_date(self) -> None:
        table = LogicalTable(
            code="8-1-3-2",
            title="사이버교육",
            title_en="",
            section_title="",
            section_title_en="",
            section_file="Contents/section1.xml",
            table_order=1,
            metadata_context="(2025. 12. 31. 기준)",
            parts=[
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[["구분", "개", "회"], ["과정", "10", "20"]],
                    raw_text="(단위 : 개, 회, 명)",
                )
            ],
        )

        imported = prepare_hwpx_import_tables([table])

        self.assertEqual(imported[0].unit, "개, 회, 명")
        self.assertEqual(imported[0].base_date, "2025. 12. 31.")

    def test_report_year_supplies_default_base_date_when_unit_exists(self) -> None:
        table = LogicalTable(
            code="8-1-3-2",
            title="사이버교육",
            title_en="",
            section_title="",
            section_title_en="",
            section_file="Contents/section1.xml",
            table_order=1,
            parts=[
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[["구분", "개"], ["과정", "10"]],
                    raw_text="(단위 : 개)",
                )
            ],
        )

        imported = prepare_hwpx_import_tables([table], report_year=2026)

        self.assertEqual(imported[0].base_date, "2025. 12. 31.")

    def test_note_continuation_with_reference_standard_is_not_metadata(self) -> None:
        note_line = "- 기상 가뭄: 기상청(관계부처 합동, 예･경보 기준)"

        self.assertFalse(is_metadata_text(note_line))
        self.assertTrue(
            is_note_continuation_text(note_line, ["#주) 지표출처 및 작성근거"])
        )

        table = LogicalTable(
            code="7-2-7",
            title="가뭄정보통계",
            title_en="",
            section_title="",
            section_title_en="",
            section_file="Contents/section1.xml",
            table_order=1,
            notes=[
                "#주) 지표출처 및 작성근거",
                note_line,
            ],
            metadata_context="",
            parts=[
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[["지역", "관심"], ["합계", "13"]],
                    raw_text="(2023. 12. 31. 기준)(단위 : 발령 횟수)",
                )
            ],
        )

        imported = prepare_hwpx_import_tables([table], report_year=2026)

        self.assertIn("기상 가뭄", imported[0].note)
        self.assertNotIn("기상 가뭄", table.metadata_context)

    def test_appendix_three_keeps_confirmed_ledger_source(self) -> None:
        self.assertEqual(
            normalize_table_sources(
                "부록 3",
                [
                    "성과관리담당관실 주무관 라현서 (044-205-1439)",
                    "혁신행정담당관실 주무관 허재은 (044-205-1439)",
                ],
            ),
            ["혁신행정담당관실 주무관 허재은 (044-205-1439)"],
        )

    def test_unknown_future_appendix_three_source_is_preserved(self) -> None:
        self.assertEqual(
            normalize_table_sources(
                "부록 3",
                ["미래담당관실 주무관 신규 (044-000-0000)"],
            ),
            ["미래담당관실 주무관 신규 (044-000-0000)"],
        )

    def test_single_importable_appendix_part_keeps_base_code(self) -> None:
        table = LogicalTable(
            code="부록 6",
            title="행정안전부 국외 양해각서(MOU) 체결",
            title_en="",
            section_title="",
            section_title_en="",
            section_file="Contents/section1.xml",
            table_order=1,
            parts=[
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[
                        ["구분", "2022", "2023"],
                        ["계", "75", "79"],
                    ],
                    raw_text="",
                ),
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[["주석만 있는 조각"]],
                    raw_text="",
                ),
            ],
        )

        imported = prepare_hwpx_import_tables([table])

        self.assertEqual([item.code for item in imported], ["부록 6"])

    def test_multiple_importable_appendix_parts_keep_part_codes(self) -> None:
        table = LogicalTable(
            code="부록 6",
            title="행정안전부 국외 양해각서(MOU) 체결",
            title_en="",
            section_title="",
            section_title_en="",
            section_file="Contents/section1.xml",
            table_order=1,
            parts=[
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[
                        ["구분", "2022", "2023"],
                        ["계", "75", "79"],
                    ],
                    raw_text="",
                ),
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[
                        ["지역", "건수"],
                        ["미국", "12"],
                    ],
                    raw_text="",
                ),
            ],
        )

        imported = prepare_hwpx_import_tables([table])

        self.assertEqual([item.code for item in imported], ["부록 6 표1", "부록 6 표2"])

    def test_two_row_one_year_table_is_data(self) -> None:
        self.assertTrue(
            is_data_table(
                [
                    ["연도", "합계", "기타"],
                    ["2022", "5,602", "125"],
                ]
            )
        )

    def test_subtable_captions_split_same_header_tables(self) -> None:
        table = LogicalTable(
            code="4-1-8-8",
            title="균형인사 임용",
            title_en="",
            section_title="",
            section_title_en="",
            section_file="Contents/section1.xml",
            table_order=1,
            parts=[
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[
                        ["▫취약계층 임용", "", ""],
                        ["연도", "2024", "2025"],
                        ["장애인", "243", "269"],
                    ],
                    raw_text="",
                ),
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[
                        ["▫장애인 고용 비율", "", ""],
                        ["연도", "2024", "2025"],
                        ["비율", "3.7", "3.6"],
                    ],
                    raw_text="",
                ),
            ],
        )

        imported = prepare_hwpx_import_tables([table])

        self.assertEqual([item.code for item in imported], ["4-1-8-8 표1", "4-1-8-8 표2"])
        self.assertEqual(imported[0].matrix[0], ["연도", "2024", "2025"])
        self.assertEqual(imported[1].matrix[0], ["연도", "2024", "2025"])

    def test_bilingual_reference_caption_is_not_stored_as_a_header_row(self) -> None:
        table = LogicalTable(
            code="5-2-1-5",
            title="조세부담률",
            title_en="Tax Burden Ratio",
            section_title="",
            section_title_en="",
            section_file="Contents/section1.xml",
            table_order=1,
            parts=[
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[
                        ["※ 2023년 외국의 조세부담률 Tax Burden Ratio of Foreign Countries", ""],
                        ["국가\nNation", "미국\nUSA"],
                        ["조세부담률", "19.1"],
                    ],
                    raw_text="",
                    footnote_matrix=[["1)", ""], ["", ""], ["", ""]],
                )
            ],
        )

        imported = prepare_hwpx_import_tables([table])

        self.assertEqual(imported[0].matrix[0], ["국가\nNation", "미국\nUSA"])
        self.assertEqual(imported[0].footnote_matrix[0], ["", ""])

    def test_multiple_subtables_inside_one_hwpx_table_are_split(self) -> None:
        table = LogicalTable(
            code="2-2-12-3",
            title="공무용차량",
            title_en="",
            section_title="",
            section_title_en="",
            section_file="Contents/section1.xml",
            table_order=1,
            parts=[
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[
                        ["▫공용차량 정수", "", ""],
                        ["구분", "계", "승용차"],
                        ["차량 수", "32,274", "16,474"],
                        ["▫공용차량 증가 추세", "", ""],
                        ["연도", "정수", "증감"],
                        ["2025", "32,274", "162"],
                    ],
                    raw_text="",
                )
            ],
        )

        imported = prepare_hwpx_import_tables([table])

        self.assertEqual([item.code for item in imported], ["2-2-12-3 표1", "2-2-12-3 표2"])
        self.assertEqual(imported[0].matrix, [["구분", "계", "승용차"], ["차량 수", "32,274", "16,474"]])
        self.assertEqual(imported[1].matrix, [["연도", "정수", "증감"], ["2025", "32,274", "162"]])
        self.assertTrue(imported[0].raw_context.startswith("▫공용차량 정수"))
        self.assertTrue(imported[1].raw_context.startswith("▫공용차량 증가 추세"))

    def test_parent_title_context_supplies_separate_section_heading(self) -> None:
        contexts: dict[str, tuple[str, str]] = {}
        remember_title_context(
            (
                "2-1-4-1",
                "가입자 수",
                "",
                "혜택알리미",
                "Subsidies 24",
            ),
            contexts,
        )
        self.assertEqual(
            resolve_title_section(
                ("2-1-4-2", "맞춤 안내 수준 현황", "", "", ""),
                contexts,
            ),
            ("혜택알리미", "Subsidies 24"),
        )

    def test_parenthesized_header_fragments_are_joined(self) -> None:
        cell = ET.fromstring(
            """
            <tc>
              <p><run><t>계(</t></run></p>
              <p><run><t>A+B)</t></run></p>
              <p><run><t>Total</t></run></p>
            </tc>
            """
        )

        self.assertEqual(cell_text_with_footnote(cell, set())[0], "계(A+B)\nTotal")

    def test_embedded_contact_row_is_metadata_not_table_data(self) -> None:
        table = LogicalTable(
            code="2-2-9",
            title="온나라시스템 구축 기관",
            title_en="",
            section_title="",
            section_title_en="",
            section_file="Contents/section1.xml",
            table_order=1,
            parts=[
                TablePart(
                    section_file="Contents/section1.xml",
                    matrix=[
                        ["구분", "기관"],
                        ["중앙행정기관", "행정안전부"],
                        ["* 정보공개과 주무관 이혜민 (044-205-2417)", ""],
                    ],
                    raw_text="",
                )
            ],
            sources=["* 정보공개과 주무관 이혜민 (044-205-2417)"],
        )

        imported = prepare_hwpx_import_tables([table])

        self.assertEqual(imported[0].matrix, [["구분", "기관"], ["중앙행정기관", "행정안전부"]])
        self.assertIn("주무관 이혜민", imported[0].source)

    def test_organization_data_row_is_not_promoted_to_header_by_gye_syllable(self) -> None:
        self.assertFalse(
            row_looks_like_header_continuation(
                [
                    "중앙행정기관 및 위원회\nCentral Government Organizations\n(73)",
                    "행정안전부, 외교부, 기획재정부",
                ]
            )
        )
        self.assertTrue(
            row_looks_like_header_continuation(
                ["구분\nClassification", "계\nTotal"]
            )
        )


if __name__ == "__main__":
    unittest.main()
