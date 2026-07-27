from pathlib import Path
import tempfile
import unittest

from app.ingest.markdown_importer import parse_markdown, prepare_markdown_import_tables


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


if __name__ == "__main__":
    unittest.main()
