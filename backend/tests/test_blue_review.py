from pathlib import Path
import json
import tempfile
import unittest
import zipfile

from app.db.connection import connect
from app.db.schema import init_db
from app.services.database_report_service import (
    build_columns,
    build_rows,
    clean_label,
    display_header_count_from_matrix,
    english_label,
    leading_label_column_indexes,
    part_caption_from_raw_context,
    remove_unmatched_closing_parentheses,
    split_bilingual_display_value,
)
from app.validation.blue_review import (
    BLUE_REVIEW_TYPE,
    classify_blue_review_value,
    extract_blue_review_candidates,
    insert_blue_review,
    is_blue_review_candidate,
    row_context_matches,
    cell_context_matches,
    should_skip_blue_review,
    synchronize_blue_review_checks,
)
from app.validation.llm_translation_review import apply_reusable_linguistic_reviews
from app.validation.region_glossary import region_review_decision


class BlueReviewExtractionTests(unittest.TestCase):
    def test_appendix_blue_cells_and_english_marker_are_retained(self) -> None:
        header = """
        <header><charPr id="1" textColor="#0000FF"/><charPr id="2" textColor="#000000"/></header>
        """
        section = """
        <sec>
          <tbl><tr><tc><p><run charPrIDRef="2"><t>부록3 행정안전부 소속 위원회</t></run></p></tc></tr></tbl>
          <tbl><tr>
            <tc><cellAddr rowAddr="4" colAddr="0"/><p><run charPrIDRef="1"><t>지방공기업정책위원회</t></run></p></tc>
            <tc><cellAddr rowAddr="4" colAddr="1"/><p><run charPrIDRef="1"><t>15</t></run></p></tc>
          </tr></tbl>
          <tbl><tr><tc><p><run charPrIDRef="2"><t>2-1-4-1 가입자 수</t></run><run charPrIDRef="1"><t>(영문)</t></run></p></tc></tr></tbl>
        </sec>
        """
        with tempfile.TemporaryDirectory() as directory:
            hwpx_path = Path(directory) / "sample.hwpx"
            with zipfile.ZipFile(hwpx_path, "w") as archive:
                archive.writestr("Contents/header.xml", header)
                archive.writestr("Contents/section0.xml", section)

            candidates = extract_blue_review_candidates(hwpx_path)

        appendix_candidates = [candidate for candidate in candidates if candidate.table_code == "부록 3"]
        self.assertEqual(
            [candidate.text for candidate in appendix_candidates],
            ["지방공기업정책위원회", "15"],
        )
        self.assertEqual(appendix_candidates[0].source_row_index, 4)
        self.assertEqual(appendix_candidates[0].source_col_index, 0)
        self.assertTrue(
            any(candidate.table_code == "2-1-4-1" and candidate.text == "가입자 수" for candidate in candidates)
        )

    def test_row_context_prevents_repeated_value_from_matching_other_rows(self) -> None:
        source_row = "지방공기업정책위원회 | 지방공기업법 제78조의5 | 차관 | 15 | 자문 Consultation"
        self.assertTrue(
            row_context_matches(
                source_row,
                source_row,
                "자문 Consultation",
            )
        )
        self.assertFalse(
            row_context_matches(
                "국가기록관리위원회 | 공공기록물 관리에 관한 법률 제15조 | 민간인 | 20 | 자문 Consultation",
                source_row,
                "자문 Consultation",
            )
        )

    def test_blue_candidates_are_exposed_once_even_when_language_review_is_pending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                report_id = connection.execute(
                    """
                    INSERT INTO annual_reports (
                        year, title, source_file_name, source_file_path, file_hash, imported_at
                    ) VALUES (2026, '연보', 'draft.hwpx', 'draft.hwpx', 'blue-test', '2026-07-15')
                    """
                ).lastrowid
                table_id = connection.execute(
                    """
                    INSERT INTO stat_tables (report_id, code, title, table_order)
                    VALUES (?, '부록 3', '위원회 현황', 1)
                    """,
                    (report_id,),
                ).lastrowid
                run_id = connection.execute(
                    """
                    INSERT INTO validation_runs (
                        report_id, rules_version, started_at, completed_at, issue_count
                    ) VALUES (?, 'test', '2026-07-15', '2026-07-15', 0)
                    """,
                    (report_id,),
                ).lastrowid
                normal = json.dumps(
                    {
                        "status": "정상",
                        "expected_value": "자문 Consultation",
                        "difference": "공식 사전 일치",
                        "detail": "공식 표기와 일치합니다.",
                    },
                    ensure_ascii=False,
                )
                connection.execute(
                    """
                    INSERT INTO linguistic_review_candidates (
                        run_id, table_id, review_type, candidate_kind, location,
                        row_index, col_index, current_value, status, review_result_json
                    ) VALUES (?, ?, ?, 'blue_text_bilingual', '5행 5열', 4, 4, ?, 'reviewed', ?)
                    """,
                    (run_id, table_id, BLUE_REVIEW_TYPE, "자문 Consultation", normal),
                )
                connection.execute(
                    """
                    INSERT INTO linguistic_review_candidates (
                        run_id, table_id, review_type, candidate_kind, location,
                        row_index, col_index, current_value, status
                    ) VALUES (?, ?, ?, 'blue_text_korean_translation',
                              '6행 1열', 5, 0, '지방공기업정책위원회', 'pending')
                    """,
                    (run_id, table_id, BLUE_REVIEW_TYPE),
                )
                connection.commit()

            inserted = synchronize_blue_review_checks(db_path, run_id=int(run_id))

            with connect(db_path) as connection:
                checks = connection.execute(
                    """
                    SELECT location, status, expected_value, row_index, col_index
                    FROM validation_checks
                    WHERE run_id = ? AND check_type = '파란색 표기 확인'
                    ORDER BY location
                    """,
                    (run_id,),
                ).fetchall()
                issue_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM validation_issues WHERE run_id = ?",
                    (run_id,),
                ).fetchone()["count"]

        self.assertEqual(inserted, 2)
        self.assertEqual(
            [(row["location"], row["status"], row["row_index"], row["col_index"]) for row in checks],
            [
                ("5행 5열", "확인 필요", 4, 4),
                ("6행 1열", "재검수 필요", 5, 0),
            ],
        )
        self.assertEqual(checks[0]["expected_value"], "통과")
        self.assertEqual(issue_count, 2)

    def test_numeric_and_metadata_blue_marks_are_not_candidates(self) -> None:
        self.assertTrue(should_skip_blue_review("4행 2열", "3,456"))
        self.assertTrue(should_skip_blue_review("4행 2열", "12.5%"))
        self.assertFalse(should_skip_blue_review("4행 2열", "‘25.3.6."))
        self.assertFalse(should_skip_blue_review("4행 2열", "‘25.3.21.~30."))
        self.assertTrue(should_skip_blue_review("출처", "안전정책과 주무관 홍길동"))
        self.assertTrue(should_skip_blue_review("주석", "잠정치임"))
        self.assertFalse(should_skip_blue_review("4행 2열", "전자메가폰 Electronic Megaphone"))

    def test_hwpx_memo_payload_does_not_block_blue_cell_matching(self) -> None:
        source_cell = (
            "서울역2 Seoul Station2 "
            "0MEMO/65535/35/1565104720/31264680/user/\\;;"
            "memo3535user655352026-07-09T22:39:28Z번역이전구축"
        )

        self.assertTrue(
            cell_context_matches(
                "서울역2 Seoul Station2 이전구축",
                source_cell,
                "이전구축",
            )
        )

    def test_long_blue_region_lists_are_kept_for_dictionary_review(self) -> None:
        region_list = ", ".join(f"서울특별시 테스트구{i}" for i in range(220))
        self.assertTrue(is_blue_review_candidate(region_list))

    def test_embedded_latin_unit_is_not_mistaken_for_bilingual_translation(self) -> None:
        kind, korean, english = classify_blue_review_value(
            "산림작물 3,419ha 등 복구지원액 1조8,809억원"
        )

        self.assertEqual(kind, "blue_text_korean_translation")
        self.assertEqual(korean, "산림작물 3,419ha 등 복구지원액 1조8,809억원")
        self.assertEqual(english, "")

    def test_insert_blue_review_persists_one_combined_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                report_id = connection.execute(
                    """
                    INSERT INTO annual_reports (
                        year, title, source_file_name, source_file_path, file_hash, imported_at
                    ) VALUES (2026, '연보', 'draft.hwpx', 'draft.hwpx', 'insert-blue', '2026-07-16')
                    """
                ).lastrowid
                table_id = connection.execute(
                    "INSERT INTO stat_tables (report_id, code, title) VALUES (?, '1-1', '표')",
                    (report_id,),
                ).lastrowid
                run_id = connection.execute(
                    """
                    INSERT INTO validation_runs (report_id, rules_version, started_at, completed_at)
                    VALUES (?, 'test', '2026-07-16', '2026-07-16')
                    """,
                    (report_id,),
                ).lastrowid

                self.assertTrue(
                    insert_blue_review(
                        connection,
                        run_id=int(run_id),
                        table_id=int(table_id),
                        location="2행 1열",
                        row_index=1,
                        col_index=0,
                        current_value="서울 Seoul",
                    )
                )
                rows = connection.execute(
                    """
                    SELECT review_type, candidate_kind
                    FROM linguistic_review_candidates
                    WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchall()

        self.assertEqual(
            [(row["review_type"], row["candidate_kind"]) for row in rows],
            [(BLUE_REVIEW_TYPE, "blue_text_bilingual")],
        )

    def test_region_dictionary_corrects_romanization_without_llm(self) -> None:
        current = "인천 남동구, 충남 천안시, 제주 서귀포시 Inchoen Namdong-gu, Chungnam Choenan-si, Jeju Seoguipo-si"
        decision = region_review_decision(current)

        self.assertIsNotNone(decision)
        self.assertEqual(decision.status, "확인 필요")  # type: ignore[union-attr]
        self.assertEqual(
            decision.expected_value,  # type: ignore[union-attr]
            "인천 남동구, 충남 천안시, 제주 서귀포시 Incheon Namdong-gu, Chungnam Cheonan-si, Jeju Seogwipo-si",
        )

    def test_region_dictionary_uses_current_official_province_names(self) -> None:
        current = "강원특별자치도, 전북특별자치도"
        decision = region_review_decision(current)

        self.assertIsNotNone(decision)
        self.assertEqual(
            decision.expected_value,  # type: ignore[union-attr]
            "Gangwon State, Jeonbuk State",
        )

    def test_region_dictionary_handles_eup_myeon_dong_and_invalid_suffix(self) -> None:
        idong = region_review_decision("경기 포천시 이동면")
        grouped = region_review_decision(
            "경기 가평군, 충남 서산시·예산시, 전남 담양군, 경남 산청군·합천군"
        )

        self.assertIsNotNone(idong)
        self.assertEqual(
            idong.expected_value,  # type: ignore[union-attr]
            "경기 포천시 이동면 / Gyeonggi Pocheon-si Idong-myeon",
        )
        self.assertIsNotNone(grouped)
        self.assertIn("예산군", grouped.expected_value)  # type: ignore[union-attr]
        self.assertNotIn("Yesan-si", grouped.expected_value)  # type: ignore[union-attr]

    def test_region_dictionary_covers_nationwide_sgis_administrative_districts(self) -> None:
        decisions = {
            value: region_review_decision(value)
            for value in (
                "부산 해운대구",
                "부산광역시 진구",
                "강원 강릉시 주문진읍",
                "전남 구례군 간전면",
                "서울 종로구 사직동",
                "경기 시흥시 신현동",
                "경기 광주시 신현동",
            )
        }

        self.assertEqual(decisions["부산 해운대구"].expected_value, "Busan Haeundae-gu")  # type: ignore[union-attr]
        self.assertEqual(
            decisions["강원 강릉시 주문진읍"].expected_value,  # type: ignore[union-attr]
            "Gangwon Gangneung-si Jumunjin-eup",
        )
        self.assertEqual(decisions["부산광역시 진구"].expected_value, "Busan Busanjin-gu")  # type: ignore[union-attr]
        self.assertEqual(
            decisions["전남 구례군 간전면"].expected_value,  # type: ignore[union-attr]
            "Jeonnam Gurye-gun Ganjeon-myeon",
        )
        self.assertEqual(
            decisions["서울 종로구 사직동"].expected_value,  # type: ignore[union-attr]
            "Seoul Jongno-gu Sajik-dong",
        )
        self.assertEqual(
            decisions["경기 시흥시 신현동"].expected_value,  # type: ignore[union-attr]
            "Gyeonggi Siheung-si Sinhyeon-dong",
        )
        self.assertEqual(
            decisions["경기 광주시 신현동"].expected_value,  # type: ignore[union-attr]
            "Gyeonggi Gwangju-si Shinhyeon-dong",
        )

    def test_reusable_reviews_resolve_blue_region_candidate_without_llm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                report_id = connection.execute(
                    """
                    INSERT INTO annual_reports (
                        year, title, source_file_name, source_file_path, file_hash, imported_at
                    ) VALUES (2026, '연보', 'draft.hwpx', 'draft.hwpx', 'region-test', '2026-07-18')
                    """
                ).lastrowid
                table_id = connection.execute(
                    "INSERT INTO stat_tables (report_id, code, title) VALUES (?, '7-1-6-1', '표')",
                    (report_id,),
                ).lastrowid
                run_id = connection.execute(
                    """
                    INSERT INTO validation_runs (report_id, rules_version, started_at, completed_at)
                    VALUES (?, 'test', '2026-07-18', '2026-07-18')
                    """,
                    (report_id,),
                ).lastrowid
                connection.execute(
                    """
                    INSERT INTO linguistic_review_candidates (
                        run_id, table_id, review_type, candidate_kind, location,
                        row_index, col_index, current_value, korean_text, status
                    ) VALUES (?, ?, ?, 'blue_text_korean_translation',
                              '18행 3열', 17, 2, '경남 사천시, 경남 합천군',
                              '경남 사천시, 경남 합천군', 'pending')
                    """,
                    (run_id, table_id, BLUE_REVIEW_TYPE),
                )
                connection.commit()

            counts = apply_reusable_linguistic_reviews(db_path, run_id=int(run_id))

            with connect(db_path) as connection:
                candidate = connection.execute(
                    """
                    SELECT status, reviewed_model, resolution_source, review_result_json
                    FROM linguistic_review_candidates
                    WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()

        self.assertEqual(counts[2], 1)
        self.assertEqual(candidate["status"], "reviewed")
        self.assertEqual(candidate["reviewed_model"], "region-dictionary-v1")
        self.assertEqual(candidate["resolution_source"], "region_dictionary")
        self.assertIn("Gyeongnam Sacheon-si", candidate["review_result_json"])


class TableDisplayParsingTests(unittest.TestCase):
    def test_service_description_is_kept_as_a_separate_text_column(self) -> None:
        matrix = [
            ["구분\nClassification", "서비스 내용\nService", "이용량\nUsage"],
            ["기관 A", "민원 안내", "10"],
            ["기관 B", "증명서 발급", "20"],
        ]

        label_columns = leading_label_column_indexes(matrix, 1)
        columns = build_columns(matrix, 1, label_columns)

        self.assertEqual(label_columns, [0])
        self.assertEqual([column.source_col_indexes for column in columns], [[0], [1], [2]])

    def test_bilingual_labels_support_decades_curly_apostrophes_and_suffix_hyphens(self) -> None:
        self.assertEqual(clean_label("20대\n20s"), "20대")
        self.assertEqual(english_label("20대\n20s"), "20s")
        self.assertEqual(
            english_label("50만 명 이상\n500,000 Persons or more"),
            "500,000 Persons or more",
        )
        self.assertEqual(
            clean_label("50만 명 이상\n500,000 Persons or more"),
            "50만 명 이상",
        )
        self.assertEqual(clean_label("DB 관리 DB Management"), "DB 관리")
        self.assertEqual(english_label("DB 관리 DB Management"), "DB Management")
        self.assertEqual(clean_label("대로\n-daero"), "대로")
        self.assertEqual(english_label("대로\n-daero"), "-daero")
        self.assertEqual(
            clean_label("검찰청\nPublic\nProsecutor’s Office"),
            "검찰청",
        )
        self.assertEqual(
            english_label("검찰청\nPublic\nProsecutor’s Office"),
            "Public Prosecutor’s Office",
        )
        self.assertEqual(clean_label("주민소송\nResident′s Lawsuits"), "주민소송")
        self.assertEqual(
            english_label("주민소송\nResident′s Lawsuits"),
            "Resident′s Lawsuits",
        )

    def test_korean_embedded_acronyms_and_arrows_stay_in_their_language(self) -> None:
        disaster = "가축질병(\nAI)\nLivestock disease(AI)"
        explosion = "여수산단 YNCC 3공장 폭발사고\nYNCC No. 3 Cracker Explosion in Yeosu"
        dvi = "대량재해･\nDVI Mass Disaster & DVI"
        sent = "송신\n(민간→공공기관)\nSent\n(private sector →\npublic organization)"

        self.assertEqual(clean_label(disaster), "가축질병(AI)")
        self.assertEqual(english_label(disaster), "Livestock disease(AI)")
        self.assertEqual(clean_label(explosion), "여수산단 YNCC 3공장 폭발사고")
        self.assertEqual(english_label(explosion), "YNCC No. 3 Cracker Explosion in Yeosu")
        self.assertEqual(clean_label(dvi), "대량재해･DVI")
        self.assertEqual(english_label(dvi), "Mass Disaster & DVI")
        self.assertEqual(clean_label(sent), "송신 (민간→공공기관)")
        self.assertEqual(english_label(sent), "Sent (private sector → public organization)")
        grade = "전문경력관 가군, 나군, 다군\nSpecialist Grade A/B/C"
        self.assertEqual(clean_label(grade), "전문경력관 가군, 나군, 다군")
        self.assertEqual(english_label(grade), "Specialist Grade A/B/C")

    def test_numeric_english_phrases_and_ordinals_stay_in_english_labels(self) -> None:
        age = "14세 이하\n14 years old and under"
        replacement = "2차 보충\n2nd Replacement Draft"

        self.assertEqual(clean_label(age), "14세 이하")
        self.assertEqual(english_label(age), "14 years old and under")
        self.assertEqual(clean_label(replacement), "2차 보충")
        self.assertEqual(english_label(replacement), "2nd Replacement Draft")

    def test_date_round_footnotes_stay_in_english_display_text(self) -> None:
        value = "’07.12.11.(1차)\nDec. 11, 2007 (#1)\n’08.1.18.(2차)\nJan. 18, 2008 (#2)"

        self.assertEqual(
            split_bilingual_display_value(value),
            (
                "’07.12.11.(1차) ’08.1.18.(2차)",
                "Dec. 11, 2007 (#1) Jan. 18, 2008 (#2)",
            ),
        )

    def test_damage_description_with_dates_is_not_reduced_to_dates(self) -> None:
        value = (
            "▪ 인명피해(’23.3.31.) : 사망 159명, 부상 330명\n"
            "▪ 복구지원액 : 61억원\n"
            "▪\nVictims: 159 Dead, 330 Injured (Mar. 31, 2023)\n"
            "▪\nRelief: KRW 6.1B"
        )

        self.assertEqual(
            split_bilingual_display_value(value),
            (
                "▪ 인명피해(’23.3.31.) : 사망 159명, 부상 330명 ▪ 복구지원액 : 61억원 ▪",
                "Victims: 159 Dead, 330 Injured (Mar. 31, 2023) ▪ Relief: KRW 6.1B",
            ),
        )

    def test_stacked_region_footnotes_stay_in_english_display_text(self) -> None:
        value = (
            "충남 태안･서산･보령･서천･홍성･당진(1차)\n"
            "전남 신안･무안･영광\n"
            "전북 군산･부안(2차)\n"
            "Taean, Seosan, Boryeong, Seocheon, Hongseong, and Dangjin in Chungnam (#1)\n"
            "Sinan, Muan, and Yeonggwang in Jeonnam Gunsan and Buan in Jeonbuk (#2)"
        )

        self.assertEqual(
            split_bilingual_display_value(value),
            (
                "충남 태안･서산･보령･서천･홍성･당진(1차) 전남 신안･무안･영광 전북 군산･부안(2차)",
                (
                    "Taean, Seosan, Boryeong, Seocheon, Hongseong, and Dangjin in Chungnam (#1) "
                    "Sinan, Muan, and Yeonggwang in Jeonnam Gunsan and Buan in Jeonbuk (#2)"
                ),
            ),
        )

    def test_bracketed_type_qualifiers_are_preserved_in_english_headers(self) -> None:
        type_a = "출자기관\nGovernment-funded Organizations\n[Type A]"
        type_b = "출연기관\nGovernment-funded Organizations\n[Type B]"

        self.assertEqual(clean_label(type_a), "출자기관")
        self.assertEqual(english_label(type_a), "Government-funded Organizations [Type A]")
        self.assertEqual(clean_label(type_b), "출연기관")
        self.assertEqual(english_label(type_b), "Government-funded Organizations [Type B]")

    def test_formula_markers_stay_with_both_header_languages(self) -> None:
        fiscal_year = "2026년도(A)\nFY 2026"
        balance = "2024\n연말잔액\n(d=a+b-c)\nYear-end Balance of 2024\n(d=a+b-c)"
        magnitude = "2≤M＜3"

        self.assertEqual(clean_label(fiscal_year), "2026년도(A)")
        self.assertEqual(english_label(fiscal_year), "FY 2026")
        self.assertEqual(clean_label(balance), "2024 연말잔액 (d=a+b-c)")
        self.assertEqual(english_label(balance), "Year-end Balance of 2024 (d=a+b-c)")
        self.assertEqual(clean_label(magnitude), magnitude)
        self.assertIsNone(english_label(magnitude))

    def test_parenthesized_english_descriptions_and_metric_units_are_not_split(self) -> None:
        agency = "온나라시스템 구축 기관\n(Agencies Using Onnara)"
        area = "면적\n(㎡)\nExtent\n(㎡)"

        self.assertEqual(clean_label(agency), "온나라시스템 구축 기관")
        self.assertEqual(english_label(agency), "(Agencies Using Onnara)")
        self.assertEqual(clean_label(area), "면적 (㎡)")
        self.assertEqual(english_label(area), "Extent (㎡)")

    def test_parallel_descriptor_dimensions_are_not_collapsed(self) -> None:
        matrices = [
            [
                ["연도\nYear", "구분\nClassification", "합계\nTotal"],
                ["2025", "중앙행정기관", "10"],
            ],
            [
                ["구분\nClassification", "단위\nUnit", "대상\nTarget"],
                ["공공건축물", "개소", "10"],
            ],
            [
                ["생산(이관)기관\nInstruments of Production", "기록물분야\nRecord Subjects", "합계"],
                ["경찰청", "수사기록", "10"],
            ],
        ]

        for matrix in matrices:
            with self.subTest(headers=matrix[0]):
                self.assertEqual(leading_label_column_indexes(matrix, 1), [0])

    def test_split_bilingual_descriptor_column_is_presented_once(self) -> None:
        matrix = [
            ["지역\nRegion", "시·군·구\nCities Counties Districts", "", "합계\nTotal"],
            ["부산\nBusan", "서구", "Seo-gu", "3"],
            ["부산\nBusan", "남구", "Nam-gu", "1"],
            ["부산\nBusan", "해운대구", "Haeundae-gu", "2"],
        ]

        label_columns = leading_label_column_indexes(matrix, 1)
        columns = build_columns(matrix, 1, label_columns)
        rows = build_rows(matrix, columns, 1, label_column_indexes=label_columns)

        self.assertEqual(label_columns, [0])
        self.assertEqual([column.source_col_indexes for column in columns], [[0], [1, 2], [3]])
        self.assertEqual(rows[0]["c1"], "서구")
        self.assertEqual(rows[0]["c1_en"], "Seo-gu")

    def test_year_measure_header_is_not_merged_into_label_column(self) -> None:
        matrix = [
            ["구분\nClassification", "2010", "2011"],
            ["주민소환투표\nRecalls", "-", "1"],
        ]

        self.assertEqual(leading_label_column_indexes(matrix, 1), [0])

    def test_registry_descriptor_columns_are_not_collapsed(self) -> None:
        matrix = [
            ["위원회명\nName", "설치근거\nBasis for Establishment", "위원장\nChairperson", "위원수"],
            ["위원회 A", "법률 제1조", "차관", "10"],
            ["위원회 B", "법률 제2조", "민간인", "12"],
        ]
        self.assertEqual(leading_label_column_indexes(matrix, 1), [0])

    def test_total_measure_column_is_not_merged_into_the_row_label(self) -> None:
        matrix = [
            ["기준일", "", "", ""],
            ["구분\nClassification", "전체\nTotal", "최초 이용자수", ""],
            ["구분\nClassification", "전체\nTotal", "전체\nTotal", "여성\nFemale"],
            ["일반직 계", "24,266", "18,935", "13,849"],
            ["4급 이상", "-", "18", "4"],
        ]

        self.assertEqual(leading_label_column_indexes(matrix, 3), [0])

    def test_public_enterprise_headers_follow_the_source_without_invented_columns(self) -> None:
        matrix = [
            ["구분", "계", "직영기업 소계", "상수도", "하수도", "공영개발", "운송", "공사·공단 소계", "도시철도", "도시개발", "시설·환경", "기타"],
            ["계", "422", "256", "123", "105", "27", "1", "-", "166", "6", "16", "88"],
        ]

        columns = build_columns(matrix, 1, [0], table_code="5-1-9-1")

        self.assertEqual(columns[7].label, "공사·공단 소계")
        self.assertEqual(columns[8].label, "도시철도")
        self.assertEqual(columns[11].label, "기타")

    def test_unit_suffixed_measure_columns_are_not_collapsed(self) -> None:
        matrix = [
            ["구분", "건 수\nNumber of Properties", "면 적\nAreas", "금 액\nAmount"],
            ["토지", "5,473,054필지", "8,967,402,344㎡", "546,771"],
            ["건물", "216,750동", "163,526,282㎡", "157,377"],
        ]

        label_columns = leading_label_column_indexes(matrix, 1)
        columns = build_columns(matrix, 1, label_columns)

        self.assertEqual(label_columns, [0])
        self.assertEqual([column.source_col_indexes for column in columns], [[0], [1], [2], [3]])

    def test_sparse_numeric_county_column_is_not_collapsed_into_region(self) -> None:
        matrix = [
            ["지역\nRegion", "도시\nCity", "군\nCounty", "구\nDistrict"],
            ["서울", "", "-", "25"],
            ["부산", "", "1", "15"],
            ["대구", "", "2", "7"],
            ["광주", "", "-", "5"],
        ]

        self.assertEqual(leading_label_column_indexes(matrix, 1), [0, 1])

    def test_region_and_type_are_parallel_columns(self) -> None:
        matrix = [
            ["지역\nRegion", "유형\nType", "수요량\nDemand"],
            ["횡성군", "농업", "1,050"],
            ["삼척시", "생활", "800"],
        ]

        self.assertEqual(leading_label_column_indexes(matrix, 1), [0])

    def test_sparse_property_and_casualty_columns_are_measures(self) -> None:
        matrix = [
            ["지역\nRegion", "우박\n재산\nProperty", "우박\n인명\nCasualty"],
            ["서울", "-", "-"],
            ["부산", "-", "1"],
        ]

        self.assertEqual(leading_label_column_indexes(matrix, 1), [0])

    def test_ratio_formula_stays_with_korean_header_not_english_translation(self) -> None:
        raw = "국가재정\nA/(A+B)\nNational Finance"

        self.assertEqual(clean_label(raw), "국가재정 A/(A+B)")
        self.assertEqual(english_label(raw), "National Finance")

    def test_header_footnote_is_exposed_on_column_definition(self) -> None:
        columns = build_columns(
            [["연도", "활용처\nUses"], ["2025", "141"]],
            1,
            [0],
            footnote_matrix=[["", "1)"], ["", ""]],
        )

        self.assertEqual(columns[1].label, "활용처")
        self.assertEqual(columns[1].footnote_marker, "1)")

    def test_subtable_caption_stops_before_following_header_rows(self) -> None:
        self.assertEqual(
            part_caption_from_raw_context(
                "▫장애인 고용 비율\nRatio of the Disabled\n연도\nYear\n구분\nClassification"
            ),
            ("장애인 고용 비율", "Ratio of the Disabled"),
        )

    def test_subtable_caption_excludes_inline_bilingual_unit_metadata(self) -> None:
        self.assertEqual(
            part_caption_from_raw_context(
                "▫시(75개) Cities(단위 : 개)(Unit : Number)\n"
                "50만 명 이상\n500,000 Persons or more"
            ),
            ("시(75개)", "Cities"),
        )
        self.assertEqual(
            part_caption_from_raw_context(
                "※ 2025년 민방위 경보 발령현황 Civil Defense Alerts in 2025\n"
                "구분\nClassification"
            ),
            ("2025년 민방위 경보 발령현황", "Civil Defense Alerts in 2025"),
        )
        self.assertEqual(
            part_caption_from_raw_context(
                "▫ 공용차량 정수 Government Vehicles "
                "(2025. 12. 31. 기준)(As of December 31, 2025) "
                "(단위 : 대)(Unit : Vehicle) 구분\nClassification"
            ),
            ("공용차량 정수", "Government Vehicles"),
        )
        self.assertEqual(
            part_caption_from_raw_context(
                "※ 주민소송 상세내역 List of Resident’s Lawsuits "
                "구분\nClassification\n지역\nRegion"
            ),
            ("주민소송 상세내역", "List of Resident’s Lawsuits"),
        )

    def test_wide_row_oriented_text_table_uses_only_first_header_row(self) -> None:
        matrix = [
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
        ]

        header_count = display_header_count_from_matrix(matrix, 3)
        label_columns = leading_label_column_indexes(matrix, header_count)
        columns = build_columns(matrix, header_count, label_columns)
        rows = build_rows(matrix, columns, header_count, label_column_indexes=label_columns)

        self.assertEqual(header_count, 1)
        self.assertEqual(len(rows), 3)
        self.assertEqual(columns[4].label, "기타(묵념사이렌)")
        self.assertEqual(rows[0]["c0"], "울림사유")
        self.assertEqual(rows[0]["c0_en"], "Reason for alert")
        self.assertEqual(rows[2]["c4"], "안산")

    def test_blank_body_label_rows_are_not_promoted_to_display_header(self) -> None:
        matrix = [
            [
                "구분\nClassification\n지역\nRegion",
                "",
                "2024년\n연말잔액\n(a)\n2023\nBalance at the End of the Year\n(a)",
                "2025년\n적립액\n(b)\n2024\nAmount Accumulated\n(b)",
            ],
            ["합계\nTotal", "총계\nTotal", "", ""],
            ["합계\nTotal", "광역\nMetropolitan", "", ""],
            ["합계\nTotal", "시군구\nCities, Counties &\nDistricts", "", ""],
            ["서 울\nSeoul", "본청\nThe headquarter", "", ""],
            ["세 종\nSejong", "본청\nThe headquarter", "21,207", "7,828"],
        ]

        header_count = display_header_count_from_matrix(matrix, 1)
        label_columns = leading_label_column_indexes(matrix, header_count)
        columns = build_columns(matrix, header_count, label_columns)
        rows = build_rows(matrix, columns, header_count, label_column_indexes=label_columns)

        self.assertEqual(header_count, 1)
        self.assertEqual(columns[0].label, "지역")
        self.assertEqual(columns[0].source_col_indexes, [0, 1])
        self.assertEqual(columns[1].label, "2024년 연말잔액 (a)")
        self.assertEqual(rows[0]["c0"], "합계 / 총계")
        self.assertEqual(rows[2]["c0"], "합계 / 시군구")
        self.assertEqual(rows[4]["c0"], "세 종 / 본청")
        self.assertEqual(rows[4]["c2"], 21207)
        self.assertEqual(rows[4]["c3"], 7828)

    def test_only_unmatched_closing_parentheses_are_removed(self) -> None:
        self.assertEqual(remove_unmatched_closing_parentheses("Number of Persons)"), "Number of Persons")
        self.assertEqual(remove_unmatched_closing_parentheses("Budget (KRW 100 million)"), "Budget (KRW 100 million)")
        self.assertEqual(
            remove_unmatched_closing_parentheses("기타1)", preserve_numbered_markers=True),
            "기타1)",
        )


if __name__ == "__main__":
    unittest.main()
