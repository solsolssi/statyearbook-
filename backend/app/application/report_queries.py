from __future__ import annotations

from app.models.report import (
    ReportOverviewPayload,
    ReportPayload,
    StatTable,
    TableDownloadCatalogItem,
)
from app.services.database_report_service import DatabaseReportService


class ReportQueryService:
    """Read-side application boundary used by HTTP and future workers."""

    def __init__(self, repository: DatabaseReportService | None = None) -> None:
        self._repository = repository or DatabaseReportService()

    def overview(self, report_id: int | None = None) -> ReportOverviewPayload:
        return self._repository.get_overview_for_report(report_id)

    def legacy_payload(self, report_id: int | None = None) -> ReportPayload:
        return self._repository.get_payload_for_report(report_id)

    def list_tables(self, report_id: int | None = None) -> list[StatTable]:
        return self._repository.list_tables(report_id)

    def download_catalog(self, report_id: int) -> list[TableDownloadCatalogItem]:
        return self._repository.list_download_catalog(report_id)

    def table_detail(self, table_id: str, report_id: int | None = None) -> StatTable | None:
        return self._repository.get_table(table_id, report_id)
