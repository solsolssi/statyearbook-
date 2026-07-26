from __future__ import annotations

from dataclasses import is_dataclass
import unittest

from app.domain.enums import (
    JobStatus,
    LanguageReviewStatus,
    ProfileStatus,
    Severity,
    TableStatus,
    ValidationStatus,
)
from app.domain.parsed import ParsedCell, ParsedReport, ParsedTable
from app.domain.validation import HighlightTarget, LanguageCandidate, ValidationResult, ValidationSpec
from app.ingest.repository import ImportedTable
from app.validation.models import ValidationCheckRecord


class DomainModelsTest(unittest.TestCase):
    def test_parser_contract_is_shared_by_all_importers(self) -> None:
        self.assertIs(ImportedTable, ParsedTable)
        self.assertTrue(is_dataclass(ParsedCell))
        self.assertTrue(is_dataclass(ParsedReport))

    def test_validation_contract_replaces_check_record_without_breaking_callers(self) -> None:
        self.assertIs(ValidationCheckRecord, ValidationResult)
        result = ValidationCheckRecord(
            table_id=1,
            rule_id="sample.sum",
            check_type="합계 검수",
            check_label="행 합계",
            location="합계 / 2025",
            current_value="10",
            expected_value="10",
            difference="0",
            status=ValidationStatus.NORMAL,
            severity=Severity.INFO,
            detail="정상",
            highlights=(HighlightTarget(row_index=1, col_index=2),),
        )
        self.assertEqual(result.status, "정상")
        self.assertEqual(result.severity, "info")

    def test_shared_status_enums_keep_existing_wire_values(self) -> None:
        self.assertEqual(TableStatus.NEEDS_REVIEW, "needs_review")
        self.assertEqual(ValidationStatus.SUSPECTED_ERROR, "오류 의심")
        self.assertEqual(ProfileStatus.APPROVED, "approved")
        self.assertEqual(JobStatus.COMPLETED, "completed")
        self.assertEqual(LanguageReviewStatus.PENDING, "대기")
        self.assertTrue(is_dataclass(ValidationSpec))
        self.assertTrue(is_dataclass(LanguageCandidate))


if __name__ == "__main__":
    unittest.main()
