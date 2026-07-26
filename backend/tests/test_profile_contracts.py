from __future__ import annotations

import unittest

from app.domain.enums import HighlightRole
from app.validation.curated_profiles import curated_profiles
from app.validation.highlights import HighlightResolver
from app.validation.models import ValidationCell, ValidationTable
from app.validation.profile_generation.providers import ProfileProvider
from app.validation.profile_migrations import migrate_profile_document
from app.validation.profile_repository import validated_profile_draft
from app.validation.profile_rules import ProfileSpecRule
from app.validation.profile_specs import PROFILE_DOCUMENT_VERSION, validate_profile_specs
from app.validation.profiles import (
    GPTProfileDraftProvider,
    HeuristicProfileDraftProvider,
    ProfileDraft,
    ValidationProfile,
)


def make_table() -> ValidationTable:
    values = [
        ["구분", "계", "A", "B"],
        ["합계", "10", "4", "6"],
        ["미입력 항목", "-", "-", "-"],
    ]
    return ValidationTable(
        id=1,
        report_id=1,
        code="test-1",
        title="테스트",
        unit="건",
        base_date="2025. 12. 31.",
        source="담당자",
        note="",
        cells=[
            ValidationCell(
                row_index=row_index,
                col_index=col_index,
                text_value=value,
                numeric_value=None,
                is_header=row_index == 0,
            )
            for row_index, row in enumerate(values)
            for col_index, value in enumerate(row)
        ],
    )


class ProfileContractTests(unittest.TestCase):
    def test_legacy_profile_document_is_migrated_without_changing_checks(self) -> None:
        source = {
            "version": "validation-profile-v3",
            "checks": [
                {
                    "id": "profile.test.row_sum",
                    "type": "row_sum",
                    "target_column": 1,
                    "operand_columns": [2, 3],
                }
            ],
        }

        migrated = migrate_profile_document(source)

        self.assertEqual(migrated["version"], PROFILE_DOCUMENT_VERSION)
        self.assertEqual(migrated["checks"][0]["spec_version"], 1)
        self.assertEqual(migrated["checks"][0]["operand_columns"], [2, 3])

    def test_invalid_generated_spec_is_quarantined_for_review(self) -> None:
        table = make_table()
        draft = ProfileDraft(
            table_code=table.code,
            table_title=table.title,
            structure_signature="signature",
            table_type="general",
            status="ready",
            source="test",
            rules={
                "version": PROFILE_DOCUMENT_VERSION,
                "checks": [
                    {
                        "id": "profile.test.invalid",
                        "type": "row_sum",
                        "target_column": 1,
                        "operand_columns": [],
                    }
                ],
            },
            notes="",
        )

        validated = validated_profile_draft(table, draft)

        self.assertEqual(validated.status, "needs_review")
        self.assertEqual(validated.rules["checks"], [])
        self.assertEqual(len(validated.rules["invalid_checks"]), 1)

    def test_typed_spec_validation_rejects_coordinates_outside_the_table(self) -> None:
        result = validate_profile_specs(
            [
                {
                    "id": "profile.test.bad-coordinate",
                    "type": "row_sum",
                    "target_column": 8,
                    "operand_columns": [2, 3],
                }
            ],
            table=make_table(),
        )

        self.assertEqual(result.valid_specs, [])
        self.assertIn("표 범위를 벗어났습니다", result.errors[0].message)

    def test_same_table_source_coordinates_are_validated(self) -> None:
        result = validate_profile_specs(
            [
                {
                    "id": "profile.test.bad-source-row",
                    "type": "row_year_over_year_rate",
                    "target_row": 1,
                    "source_row": 20,
                    "columns": [1, 2],
                }
            ],
            table=make_table(),
        )

        self.assertEqual(result.valid_specs, [])
        self.assertIn("source_row=20", result.errors[0].message)

    def test_heuristic_and_llm_generators_share_the_provider_contract(self) -> None:
        self.assertIsInstance(HeuristicProfileDraftProvider(), ProfileProvider)
        self.assertIsInstance(GPTProfileDraftProvider(), ProfileProvider)

    def test_chapter_curated_profiles_are_loaded_as_one_catalog(self) -> None:
        profiles = curated_profiles()

        self.assertIn("1-2-1-2", profiles)
        self.assertIn("8-1-1-3", profiles)

    def test_highlight_plan_preserves_dash_operands_with_semantic_roles(self) -> None:
        table = make_table()
        row = {"row_index": 2, "col_index": 1}
        spec = {
            "id": "profile.test.row_sum",
            "type": "row_sum",
            "target_column": 1,
            "operand_columns": [2, 3],
        }

        plan = HighlightResolver().plan(
            row,  # type: ignore[arg-type]
            spec=spec,
            header_count=table.header_count,
            matrix=table.matrix,
        )

        self.assertEqual(
            {(item.row_index, item.col_index, item.role) for item in plan.targets},
            {(2, 1, HighlightRole.TARGET)},
        )
        self.assertEqual(
            {(item.row_index, item.col_index, item.role) for item in plan.operands},
            {
                (2, 2, HighlightRole.OPERAND),
                (2, 3, HighlightRole.OPERAND),
            },
        )
        public_cells = HighlightResolver.presentation_cells(plan)
        self.assertEqual(
            {(item.row_index, item.col_index, str(item.role)) for item in public_cells},
            {
                (2, 1, "target"),
                (2, 2, "related"),
                (2, 3, "related"),
            },
        )

    def test_profile_rule_result_records_target_and_operand_roles(self) -> None:
        table = make_table()
        profile = ValidationProfile(
            id=1,
            table_code=table.code,
            table_title=table.title,
            source_report_id=table.report_id,
            structure_signature="signature",
            table_type="general",
            status="ready",
            source="test",
            rules={},
            notes="",
            created_at="",
            updated_at="",
        )
        spec = {
            "id": "profile.test.row_sum",
            "type": "row_sum",
            "label": "계 = A + B",
            "target_column": 1,
            "operand_columns": [2, 3],
        }

        result = ProfileSpecRule({})._check_record(
            table,
            profile,
            spec,
            check_type="합계 검수",
            location="미입력 항목 / 계",
            current_value="-",
            expected_value="0",
            difference=None,
            status="정상",
            severity="info",
            detail="합계를 확인했습니다.",
            row_index=2,
            col_index=1,
            formula="계 = A + B",
        )

        self.assertEqual(
            [item.role for item in result.highlights],
            [HighlightRole.TARGET, HighlightRole.OPERAND, HighlightRole.OPERAND],
        )


if __name__ == "__main__":
    unittest.main()
