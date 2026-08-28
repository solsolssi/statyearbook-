from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.db.connection import connect
from app.db.schema import classify_glossary_approval_metadata, init_db
from app.validation.blue_review import insert_blue_review
from app.validation.language_pipeline.execution import ReviewBatchExecutor
from app.validation.language_pipeline.models import SourceReviewItem
from app.validation.language_pipeline.responses import validated_review_items
from app.validation.language_pipeline.storage import (
    LLMUsageRepository,
    usage_event_from_response,
)


class LanguagePipelineTest(unittest.TestCase):
    def test_glossary_governance_metadata_is_backfilled(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "glossary.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                connection.execute(
                    """
                    INSERT INTO translation_glossary (
                        origin_key, source_text, source_normalized,
                        target_text, target_normalized, source_kind, status
                    )
                    VALUES (
                        'official:test', '서울', '서울',
                        'Seoul', 'seoul', 'official', 'official_verified'
                    )
                    """
                )
                classify_glossary_approval_metadata(connection)
                row = connection.execute(
                    """
                    SELECT approval_status, approved_by, glossary_version
                    FROM translation_glossary
                    WHERE origin_key = 'official:test'
                    """
                ).fetchone()

            assert row is not None
            self.assertEqual(row["approval_status"], "approved")
            self.assertEqual(row["approved_by"], "official_source")
            self.assertEqual(row["glossary_version"], 1)

    def test_blue_candidate_records_explicit_source_kind(self) -> None:
        with TemporaryDirectory() as directory:
            db_path = Path(directory) / "language.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                report_id = int(
                    connection.execute(
                        """
                        INSERT INTO annual_reports (
                            year, title, source_file_name, source_file_path,
                            file_hash, imported_at
                        )
                        VALUES (2026, '연보', 'draft.hwpx', 'draft.hwpx', 'hash', '2026-07-26')
                        """
                    ).lastrowid
                )
                table_id = int(
                    connection.execute(
                        """
                        INSERT INTO stat_tables (report_id, code, title, table_order)
                        VALUES (?, '1-1', '표', 1)
                        """,
                        (report_id,),
                    ).lastrowid
                )
                run_id = int(
                    connection.execute(
                        """
                        INSERT INTO validation_runs (
                            report_id, rules_version, started_at, completed_at
                        )
                        VALUES (?, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                        (report_id,),
                    ).lastrowid
                )
                self.assertTrue(
                    insert_blue_review(
                        connection,
                        run_id=run_id,
                        table_id=table_id,
                        location="표 제목",
                        row_index=None,
                        col_index=None,
                        current_value="지역 Region",
                    )
                )
                row = connection.execute(
                    """
                    SELECT source_kind, candidate_kind, review_type
                    FROM linguistic_review_candidates
                    WHERE run_id = ?
                    """,
                    (run_id,),
                ).fetchone()

            assert row is not None
            self.assertEqual(row["source_kind"], "blue")
            self.assertTrue(str(row["candidate_kind"]).startswith("blue_text"))
            self.assertEqual(row["review_type"], "파란색 표기 확인")

    def test_usage_event_records_tokens_and_configured_estimate(self) -> None:
        with TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {
                "LLM_INPUT_COST_PER_MILLION": "0.25",
                "LLM_OUTPUT_COST_PER_MILLION": "2.0",
            },
        ):
            db_path = Path(directory) / "usage.sqlite"
            with connect(db_path) as connection:
                init_db(connection)
                report_id = int(
                    connection.execute(
                        """
                        INSERT INTO annual_reports (
                            year, title, source_file_name, source_file_path,
                            file_hash, imported_at
                        )
                        VALUES (2026, '연보', 'draft.xlsx', 'draft.xlsx', 'hash', '2026-07-26')
                        """
                    ).lastrowid
                )
                run_id = int(
                    connection.execute(
                        """
                        INSERT INTO validation_runs (
                            report_id, rules_version, started_at, completed_at
                        )
                        VALUES (?, 'test', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                        (report_id,),
                    ).lastrowid
                )
                connection.commit()

            event = usage_event_from_response(
                run_id=run_id,
                provider="openai",
                model="gpt-test",
                request_kind="language_review",
                response={
                    "status": "completed",
                    "usage": {
                        "input_tokens": 1_000,
                        "output_tokens": 200,
                        "total_tokens": 1_200,
                    },
                },
            )
            LLMUsageRepository(db_path).record(event)

            with connect(db_path) as connection:
                init_db(connection)
                row = connection.execute(
                    "SELECT * FROM llm_usage_events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            assert row is not None
            self.assertEqual(row["total_tokens"], 1_200)
            self.assertAlmostEqual(float(row["estimated_cost_usd"]), 0.00065)

    def test_structured_response_validation_drops_non_object_items(self) -> None:
        response = {
            "output_text": json.dumps(
                {"items": [{"id": 1, "status": "정상"}, "invalid"]},
                ensure_ascii=False,
            )
        }
        self.assertEqual(
            validated_review_items(response),
            [{"id": 1, "status": "정상"}],
        )

    def test_compact_context_response_restores_independent_review_types(self) -> None:
        response = {
            "output_text": json.dumps(
                {
                    "items": [
                        {
                            "context_token": "ctx_shared",
                            "reviews": [
                                {
                                    "id": 11,
                                    "status": "오류 의심",
                                    "defect_kind": "spacing",
                                    "expected_value": "of a",
                                    "difference": "띄어쓰기 오류",
                                    "detail": "영문 띄어쓰기를 교정했습니다.",
                                },
                                {
                                    "id": 12,
                                    "status": "확인 필요",
                                    "defect_kind": "wrong_meaning",
                                    "expected_value": "correct translation",
                                    "difference": "의미 불일치",
                                    "detail": "국문과 영문의 의미가 다릅니다.",
                                },
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        }

        decisions = validated_review_items(
            response,
            requested_review_types={11: "오탈자 검수", 12: "번역 검수"},
        )

        self.assertEqual(len(decisions), 2)
        self.assertEqual(decisions[0]["context_token"], "ctx_shared")
        self.assertEqual(decisions[0]["issue_type"], "오탈자 검수")
        self.assertEqual(decisions[1]["issue_type"], "번역 검수")

    def test_batch_executor_keeps_decisions_bound_to_candidate_ids(self) -> None:
        item = self.review_item()

        class Client:
            calls = 0

            def review(self, items, *, require_english_replacement=False):
                self.calls += 1
                return [{"id": items[0].issue_id, "status": "정상"}]

        client = Client()
        executor = ReviewBatchExecutor(
            decision_needs_retry=lambda decision, candidate: False,
            recover_decision=lambda decision, candidate: None,
            context_key=lambda candidate: (
                candidate.table_id,
                candidate.row_index,
                candidate.col_index,
            ),
        )
        self.assertEqual(executor.execute(client, [item]), [{"id": 7, "status": "정상"}])
        self.assertEqual(client.calls, 1)

    @staticmethod
    def review_item() -> SourceReviewItem:
        return SourceReviewItem(
            issue_id=7,
            source_rule_id="source.linguistic_review",
            candidate_kind="language_spelling",
            candidate_reason="",
            candidate_expected="",
            table_id=1,
            table_code="1-1",
            table_title="제목",
            table_title_en="Title",
            unit="명",
            base_date="2025. 12. 31.",
            location="2행 1열",
            row_index=1,
            col_index=0,
            current_value="서울 Seoul",
            cell_text="서울 Seoul",
            row_label="서울 Seoul",
            column_label="지역 Region",
            surrounding_rows=[],
            requested_review_type="오탈자 검수",
        )


if __name__ == "__main__":
    unittest.main()
