from __future__ import annotations

from unittest.mock import Mock
import unittest

from app.application.report_queries import ReportQueryService
from app.models.report import StatTableSummary


class ReportQueryServiceTest(unittest.TestCase):
    def test_read_operations_delegate_to_the_repository_boundary(self) -> None:
        repository = Mock()
        repository.get_overview_for_report.return_value = object()
        repository.get_payload_for_report.return_value = object()
        repository.list_tables.return_value = []
        repository.get_table.return_value = None
        service = ReportQueryService(repository)

        self.assertIs(service.overview(2026), repository.get_overview_for_report.return_value)
        self.assertIs(service.legacy_payload(2025), repository.get_payload_for_report.return_value)
        self.assertEqual(service.list_tables(2026), [])
        self.assertIsNone(service.table_detail("1-1-1-1", 2026))

        repository.get_overview_for_report.assert_called_once_with(2026)
        repository.get_payload_for_report.assert_called_once_with(2025)
        repository.list_tables.assert_called_once_with(2026)
        repository.get_table.assert_called_once_with("1-1-1-1", 2026)

    def test_overview_projection_cannot_contain_source_cells(self) -> None:
        fields = set(StatTableSummary.model_fields)

        self.assertNotIn("rows", fields)
        self.assertNotIn("columns", fields)
        self.assertNotIn("parts", fields)
        self.assertNotIn("metadata", fields)


if __name__ == "__main__":
    unittest.main()
