from pathlib import Path
import tempfile
import unittest

from app.ingest.markdown_importer import (
    extract_part_caption,
    line_is_source,
    parse_markdown,
    prepare_markdown_import_tables,
)


class MarkdownImporterTests(unittest.TestCase):
    def test_single_data_row_html_table_is_kept_as_part(self) -> None:
        content = """
7-2-5-2 연도별 무더위 쉼터 Heat Wave Shelters by Year

<table>
<tr><th colspan="3">(2025. 12. 31. 기준)(단위 : 개소)</th></tr>
<tr><td>구분<br>Classification<br>연도<br>Year</td><td>합계<br>Total</td><td>노인시설<br>Senior Facilities</td></tr>
<tr><td>2024</td><td>54,327</td><td>45,037</td></tr>
</table>

<table>
<tr><th colspan="3"></th></tr>
<tr><td>구분<br>Classification<br>지역<br>Region</td><td>공공시설</td><td>합계<br>Total</td></tr>
<tr><td>2025</td><td>7,373</td><td>62,508</td></tr>
</table>
"""
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "report.md"
            source_path.write_text(content, encoding="utf-8")

            tables = prepare_markdown_import_tables(parse_markdown(source_path))

        by_code = {table.code: table for table in tables}
        self.assertIn("7-2-5-2 표1", by_code)
        self.assertIn("7-2-5-2 표2", by_code)
        self.assertEqual(by_code["7-2-5-2 표2"].matrix[-1][0], "2025")

    def test_single_data_row_markdown_table_is_kept_as_part(self) -> None:
        content = """
7-2-8-2 연도별 인명피해 우려지역 Concerned Area of Casualties by Year

| 구분<br>Classification<br>연도<br>Year | 합계<br>Total | 산사태<br>Land<br>Slide |
| --- | --- | --- |
| 2022 | 5,602 | 776 |

| 구분<br>Classification<br>연도<br>Year | 합계<br>Total | 산사태<br>Landslide | 기타<br>Others |
| --- | --- | --- | --- |
| 2023 | 5,542 | 1,132 | 903 |
| 2024 | 7,351 | 1,684 | 838 |
"""
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "report.md"
            source_path.write_text(content, encoding="utf-8")

            tables = prepare_markdown_import_tables(parse_markdown(source_path))

        by_code = {table.code: table for table in tables}
        self.assertIn("7-2-8-2 표1", by_code)
        self.assertIn("7-2-8-2 표2", by_code)
        self.assertEqual(by_code["7-2-8-2 표1"].matrix[-1][0], "2022")

    def test_distinct_captioned_parts_with_same_header_are_split(self) -> None:
        content = """
4-1-8-8 균형인사 임용 Balanced Recruitment of Local Governments

| ▫ 취약계층 임용 Recruitment of the Vulnerable at Local Governments | | | |
| --- | --- | --- | --- |
| 연도<br>Year<br>구분<br>Classification | 2023 | 2024 | 2025 |
| 장애인 구분모집<br>Disabled | 311 | 243 | 269 |

| ▫ 장애인 고용 비율 Ratio of the Disabled | | | |
| --- | --- | --- | --- |
| 연도<br>Year<br>구분<br>Classification | 2023 | 2024 | 2025 |
| 비 율<br>Ratio (%) | 3.80 | 3.70 | 3.60 |
"""
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "report.md"
            source_path.write_text(content, encoding="utf-8")

            tables = prepare_markdown_import_tables(parse_markdown(source_path))

        by_code = {table.code: table for table in tables}
        self.assertIn("4-1-8-8 표1", by_code)
        self.assertIn("4-1-8-8 표2", by_code)
        self.assertEqual(by_code["4-1-8-8 표1"].matrix[-1][0], "장애인 구분모집\nDisabled")
        self.assertEqual(by_code["4-1-8-8 표2"].matrix[-1][0], "비 율\nRatio (%)")

    def test_repeated_page_header_is_merged_into_one_table(self) -> None:
        content = """
7-2-10 재난·안전 정보시스템 Disaster and Safety Information System

<table>
<tr><td>시스템<br>System</td><td>부서<br>Department</td><td>기능<br>Function</td></tr>
<tr><td>시스템 A</td><td>부서 A</td><td>1</td></tr>
</table>

<table>
<tr><td>시스템<br>System</td><td>부서<br>Department</td><td>기능<br>Function</td></tr>
<tr><td>시스템 B</td><td>부서 B</td><td>2</td></tr>
</table>
"""
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "report.md"
            source_path.write_text(content, encoding="utf-8")

            tables = prepare_markdown_import_tables(parse_markdown(source_path))

        self.assertEqual([table.code for table in tables], ["7-2-10"])
        self.assertEqual([row[0] for row in tables[0].matrix], ["시스템\nSystem", "시스템 A", "시스템 B"])

    def test_bilingual_label_columns_are_not_destructively_merged(self) -> None:
        content = """
5-2-1-4 세목별 지방세 Local Tax by Tax Item

<table>
<tr><td>구분</td><td>Classification</td><td>계<br>Total</td></tr>
<tr><td>취득세</td><td>Acquisition Tax</td><td>100</td></tr>
</table>
"""
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "report.md"
            source_path.write_text(content, encoding="utf-8")

            tables = prepare_markdown_import_tables(parse_markdown(source_path))

        self.assertEqual(len(tables[0].matrix[0]), 3)
        self.assertEqual(tables[0].matrix[1][:2], ["취득세", "Acquisition Tax"])

    def test_caption_removal_preserves_visible_unit_cell(self) -> None:
        standalone, title, _ = extract_part_caption(
            [["▫ 공용차량 증가 추세", "", ""], ["연도", "정수", "증감"]]
        )
        with_unit, unit_title, _ = extract_part_caption(
            [["▫ 일반교육", "", "(단위 : 명)"], ["연도", "과정", "인원"]]
        )

        self.assertEqual(title, "공용차량 증가 추세")
        self.assertEqual(standalone[0], ["연도", "정수", "증감"])
        self.assertEqual(unit_title, "일반교육")
        self.assertEqual(with_unit[0][2], "(단위 : 명)")

        note_caption, note_title, note_title_en = extract_part_caption(
            [
                ["※ 주민소송 상세내역 List of Resident’s Lawsuits", "", ""],
                ["구분", "소송제기일", "결과"],
            ]
        )
        self.assertEqual(note_title, "주민소송 상세내역")
        self.assertEqual(note_title_en, "List of Resident’s Lawsuits")
        self.assertEqual(note_caption[0], ["구분", "소송제기일", "결과"])

    def test_contact_source_requires_role_name_and_phone(self) -> None:
        self.assertTrue(line_is_source("* 기록관리과 연구사 홍길동 (044-205-1234)"))
        self.assertTrue(line_is_source("* 운영지원과 서기관 김하늘 (044-205-5678)"))
        self.assertFalse(line_is_source("* 문의 전화는 044-205-1234입니다"))

    def test_markdown_footnotes_match_visible_markers_without_losing_values(self) -> None:
        content = """
7-1-2-4 등급별 자연재해위험개선지구 Natural Disaster Risk Improvement District by Grade

<table>
<tr><td>구분<br>Classification</td><td>가1) (인명 피해)<br>A (Personal Damage)</td><td>비율</td></tr>
<tr><td>합계</td><td>995</td><td>47.3(42.4)</td></tr>
</table>

#주1) 인명 피해 기준
"""
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "report.md"
            source_path.write_text(content, encoding="utf-8")

            tables = prepare_markdown_import_tables(parse_markdown(source_path))

        self.assertEqual(tables[0].matrix[0][1], "가 (인명 피해)\nA (Personal Damage)")
        self.assertEqual(tables[0].footnote_matrix[0][1], "1)")
        self.assertEqual(tables[0].matrix[1][2], "47.3(42.4)")


if __name__ == "__main__":
    unittest.main()
