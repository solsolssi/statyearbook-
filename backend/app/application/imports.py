from __future__ import annotations

from collections.abc import AsyncIterable

from app.services.report_import_service import ReportImportRequest, ReportImportService
from app.workflows.job_executor import JobExecutor
from app.workflows.report_processing import ReportProcessingWorkflow


class ReportImportApplicationService:
    """Coordinate upload persistence, job creation, execution and retries."""

    def __init__(
        self,
        *,
        executor: JobExecutor,
        import_service: ReportImportService | None = None,
        workflow: ReportProcessingWorkflow | None = None,
    ) -> None:
        self._executor = executor
        self._import_service = import_service or ReportImportService()
        self._workflow = workflow or ReportProcessingWorkflow()

    async def create(
        self,
        request: ReportImportRequest,
        chunks: AsyncIterable[bytes],
    ) -> dict[str, object]:
        job = await self._import_service.create_job(request, chunks)
        self._executor.submit(int(job["id"]))
        return job

    def get(self, job_id: int) -> dict[str, object] | None:
        return self._workflow.get_job(job_id)

    def retry(self, job_id: int) -> dict[str, object] | None:
        job = self._workflow.get_job(job_id)
        if job is None:
            return None
        queued = self._workflow.queue_retry(job_id)
        self._executor.submit(job_id, retry=True)
        return queued

