from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status

from app.core.config import get_settings
from app.models.report import (
    ReportOverviewPayload,
    ReportPayload,
    ReportProcessingJob,
    StatTable,
    ValidationProfileApprovalRequest,
    ValidationProfileSummary,
    ValidationCatalogItem,
    ValidationRunResult,
)
from app.application.imports import ReportImportApplicationService
from app.application.report_queries import ReportQueryService
from app.application.validation_operations import ValidationApplicationService
from app.services.report_service import get_report_service
from app.services.report_import_service import (
    ReportImportRequest,
    ReportUploadError,
)
from app.workflows.report_processing import (
    ReportProcessingError,
    ReportProcessingWorkflow,
)
from app.workflows.job_executor import InProcessJobExecutor, JobExecutor, QueuedJobExecutor

router = APIRouter()


@router.get("/report", response_model=ReportPayload)
def get_report(report_id: int | None = Query(default=None)) -> ReportPayload:
    return ReportQueryService(get_report_service()).legacy_payload(report_id)


@router.get("/report/overview", response_model=ReportOverviewPayload)
def get_report_overview(report_id: int | None = Query(default=None)) -> ReportOverviewPayload:
    return ReportQueryService(get_report_service()).overview(report_id)


@router.get("/tables", response_model=list[StatTable])
def list_tables(report_id: int | None = Query(default=None)) -> list[StatTable]:
    return ReportQueryService(get_report_service()).list_tables(report_id)


@router.get("/tables/{table_id}", response_model=StatTable)
def get_table(table_id: str, report_id: int | None = Query(default=None)) -> StatTable:
    table = ReportQueryService(get_report_service()).table_detail(table_id, report_id)
    if table is None:
        raise HTTPException(status_code=404, detail="Table not found")
    return table


@router.post("/validation/run", response_model=ValidationRunResult)
def run_validation(report_id: int | None = Query(default=None)) -> ValidationRunResult:
    return ValidationApplicationService().run(report_id)


@router.post(
    "/imports",
    response_model=ReportProcessingJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_report_import(
    request: Request,
    background_tasks: BackgroundTasks,
    filename: str = Query(min_length=1),
    year: int | None = Query(default=None, ge=1900, le=2200),
    title: str | None = Query(default=None),
    include_llm: bool | None = Query(default=None),
    refresh_profiles: bool = Query(default=False),
) -> ReportProcessingJob:
    """Stream one workbook/document into a queued import and validation job."""

    application = ReportImportApplicationService(executor=job_executor(background_tasks))
    try:
        job = await application.create(
            ReportImportRequest(
                filename=filename,
                year=year,
                title=title,
                include_llm=include_llm,
                refresh_profiles=refresh_profiles,
            ),
            request.stream(),
        )
    except ReportUploadError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    return ReportProcessingJob(**job)


@router.get("/imports/{job_id}", response_model=ReportProcessingJob)
def get_report_import(job_id: int) -> ReportProcessingJob:
    job = ReportImportApplicationService(
        executor=QueuedJobExecutor(),
    ).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="가져오기 작업을 찾을 수 없습니다.")
    return ReportProcessingJob(**job)


@router.post(
    "/imports/{job_id}/retry",
    response_model=ReportProcessingJob,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_report_import(job_id: int, background_tasks: BackgroundTasks) -> ReportProcessingJob:
    job = ReportImportApplicationService(
        executor=job_executor(background_tasks),
    ).retry(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="가져오기 작업을 찾을 수 없습니다.")
    return ReportProcessingJob(**job)


def run_processing_job(job_id: int, retry: bool = False) -> None:
    workflow = ReportProcessingWorkflow()
    try:
        if retry:
            workflow.retry(job_id)
        else:
            workflow.run(job_id)
    except ReportProcessingError:
        # The workflow already persisted the stage and error. The status API is
        # the source of truth, so a background exception must not lose context.
        return


def job_executor(background_tasks: BackgroundTasks) -> JobExecutor:
    backend = get_settings().job_executor_backend.strip().lower()
    if backend in {"queue", "queued", "worker"}:
        return QueuedJobExecutor()
    return InProcessJobExecutor(background_tasks.add_task, run_processing_job)


@router.get("/validation/profiles", response_model=list[ValidationProfileSummary])
def list_validation_profiles() -> list[ValidationProfileSummary]:
    return ValidationApplicationService().list_profiles()


@router.get("/validation/catalog", response_model=list[ValidationCatalogItem])
def get_validation_catalog() -> list[ValidationCatalogItem]:
    return ValidationApplicationService().catalog()


@router.post("/validation/profiles/{profile_id}/approve", response_model=ValidationProfileSummary)
def approve_validation_profile(
    profile_id: int,
    payload: ValidationProfileApprovalRequest,
) -> ValidationProfileSummary:
    profile = ValidationApplicationService().approve_profile(
        profile_id,
        approved_by=payload.approved_by,
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Validation profile not found")
    return profile
