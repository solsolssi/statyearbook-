from __future__ import annotations

from unittest.mock import Mock, patch
import unittest

from app.export.validation_presentation import build_validation_presentations
from app.models.report import ValidationIssue
from app.validation.models import ValidationTable


class ValidationExportPresentationTest(unittest.TestCase):
    @patch("app.export.validation_presentation.load_rule_specs_by_id")
    @patch("app.export.validation_presentation.validation_issue_from_row")
    def test_export_uses_the_same_presentation_issue_as_the_api(
        self,
        validation_issue_from_row: Mock,
        load_rule_specs_by_id: Mock,
    ) -> None:
        row = {
            "id": 17,
            "table_id": 3,
            "rule_id": "fixture.sum",
            "check_type": "합계 검수",
        }
        table = ValidationTable(
            id=3,
            report_id=1,
            code="1-1-1-1",
            title="테스트",
            unit="건",
            base_date="2025. 12. 31.",
            source="",
            note="",
            cells=[],
        )
        issue = ValidationIssue(
            id="check-17",
            rule_id="fixture.sum",
            type="합계 검수",
            location="합계 / 2025",
            current_value="10",
            expected_value="10",
            difference="0",
            status="정상",
            severity="info",
            detail="정상",
        )
        load_rule_specs_by_id.return_value = {"fixture.sum": {"type": "row_sum"}}
        validation_issue_from_row.return_value = issue

        result = build_validation_presentations(
            Mock(),
            [row],  # type: ignore[list-item]
            {3: table},
        )

        self.assertIs(result[17].issue, issue)
        validation_issue_from_row.assert_called_once_with(
            row,
            issue_id="check-17",
            check_type="합계 검수",
            header_count=0,
            matrix=[],
            spec={"type": "row_sum"},
            include_highlights=True,
        )


if __name__ == "__main__":
    unittest.main()
