from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)

from app.core.config import get_settings
from app.models.report import (
    ReportDeleteResult,
    ReportOverviewPayload,
    ReportPayload,
    ReportProcessingJob,
    StatTable,
    ValidationProfileApprovalRequest,
    ValidationProfileSummary,
    ValidationCatalogItem,
    ValidationReuseRunOption,
    ValidationRunRequest,
    ValidationRunResult,
)
from app.models.source_statistics import (
    SourceDataImportResult,
    SourceStatisticDetail,
    SourceStatisticsOverview,
)
from app.models.yearbook_reproduction import (
    ReproductionBuildSummary,
    YearbookReproductionOverview,
)
from app.models.report_updates import ReportComparisonSummary
from app.application.imports import ReportImportApplicationService
from app.application.report_queries import ReportQueryService
from app.application.validation_operations import ValidationApplicationService
from app.services.report_service import get_report_service
from app.services.database_report_service import TEST_REPORT_ID
from app.services.report_import_service import (
    ReportImportRequest,
    ReportUploadError,
)
from app.services.source_statistics_service import SourceStatisticsService
from app.services.yearbook_reproduction_service import YearbookReproductionService
from app.services.yearbook_reproduction_build_service import (
    YearbookReproductionBuildService,
)
from app.services.ledger_yearbook_service import LedgerYearbookService
from app.services.report_update_service import ReportComparisonService
from app.yearbook_data.relational_import import RelationalSourceDataImporter
from app.yearbook_data.relational_import import FULL_INFO_COLUMNS, tabular_rows
from app.workflows.report_processing import (
    ReportProcessingError,
    ReportProcessingWorkflow,
)
from app.workflows.job_executor import InProcessJobExecutor, JobExecutor, QueuedJobExecutor

router = APIRouter()


@router.get("/source-statistics", response_model=SourceStatisticsOverview)
def get_source_statistics() -> SourceStatisticsOverview:
    return SourceStatisticsService().overview()


@router.post("/source-statistics/import", response_model=SourceDataImportResult)
async def import_source_statistics(
    mode: Literal["append_year"] = Query(default="append_year"),
    base_report_id: int = Query(gt=0),
    target_year: int = Query(ge=1900, le=2200),
    title: str | None = Query(default=None, min_length=1),
    info_file: UploadFile = File(),
    item_file: UploadFile = File(),
    value_file: UploadFile = File(),
) -> SourceDataImportResult:
    """Import normalized source-system Excel exports for a selected report context."""

    with TemporaryDirectory() as directory:
        root = Path(directory)
        info_path = await save_uploaded_excel(info_file, root)
        item_path = await save_uploaded_excel(item_file, root)
        value_path = await save_uploaded_excel(value_file, root)
        headers, rows = tabular_rows(info_path)
        next(rows, None)
        rows.close()
        importer = RelationalSourceDataImporter()
        if FULL_INFO_COLUMNS.issubset(set(headers)):
            result = importer.import_full(
                info_path=info_path,
                item_path=item_path,
                value_path=value_path,
            )
        else:
            result = importer.import_delta(
                info_path=info_path,
                item_path=item_path,
                value_path=value_path,
                target_year=target_year,
            )
        generated = LedgerYearbookService().generate(
            base_report_id=base_report_id,
            target_year=target_year,
            source_batch_id=result.batch_id,
            mode=mode,
            title=title,
        )
    return SourceDataImportResult(
        mode=mode,
        base_report_id=base_report_id,
        target_year=target_year,
        generated_report_id=generated.report_id,
        reproduction_run_id=generated.reproduction_run_id,
        **result.__dict__,
    )


async def save_uploaded_excel(upload: UploadFile, directory: Path) -> Path:
    safe_name = Path(upload.filename or "").name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in {".xls", ".xlsx"}:
        raise HTTPException(status_code=415, detail=".xls, .xlsx 파일만 업로드할 수 있습니다.")
    destination = directory / safe_name
    destination.write_bytes(await upload.read())
    return destination


@router.get(
    "/yearbook-reproduction",
    response_model=YearbookReproductionOverview,
)
def get_yearbook_reproduction(
    report_id: int | None = Query(default=None),
    report_year: int | None = Query(default=None, ge=1900, le=2200),
) -> YearbookReproductionOverview:
    try:
        return YearbookReproductionService().overview(
            report_id=report_id,
            report_year=report_year,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/yearbook-reproduction/build",
    response_model=ReproductionBuildSummary,
)
def build_yearbook_reproduction(
    report_id: int = Query(),
) -> ReproductionBuildSummary:
    try:
        return YearbookReproductionBuildService().run(report_id=report_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/report-comparisons", response_model=ReportComparisonSummary)
def compare_reports(
    left_report_id: int = Query(gt=0),
    right_report_id: int = Query(gt=0),
) -> ReportComparisonSummary:
    if left_report_id == right_report_id:
        raise HTTPException(status_code=400, detail="서로 다른 두 연보를 선택해 주세요.")
    return ReportComparisonService().compare(
        left_report_id=left_report_id,
        right_report_id=right_report_id,
    )


@router.get(
    "/source-statistics/{external_id}",
    response_model=SourceStatisticDetail,
)
def get_source_statistic(
    external_id: str,
    period: str | None = Query(default=None),
) -> SourceStatisticDetail:
    detail = SourceStatisticsService().detail(external_id, period=period)
    if detail is None:
        raise HTTPException(status_code=404, detail="원장 통계를 찾을 수 없습니다.")
    return detail


@router.get("/report", response_model=ReportPayload)
def get_report(report_id: int | None = Query(default=None)) -> ReportPayload:
    return ReportQueryService(get_report_service()).legacy_payload(report_id)


@router.get("/report/overview", response_model=ReportOverviewPayload)
def get_report_overview(report_id: int | None = Query(default=None)) -> ReportOverviewPayload:
    return ReportQueryService(get_report_service()).overview(report_id)


@router.delete("/reports/{report_id}", response_model=ReportDeleteResult)
def delete_report(report_id: int) -> ReportDeleteResult:
    try:
        result = get_report_service().delete_report(report_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="삭제할 연보를 찾을 수 없습니다.")
    return result


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
def run_validation(
    payload: ValidationRunRequest | None = None,
    report_id: int | None = Query(default=None),
) -> ValidationRunResult:
    if report_id == TEST_REPORT_ID:
        raise HTTPException(
            status_code=400,
            detail="테스트 연보는 생성 상태 확인용이며 검수를 실행하지 않습니다.",
        )
    request = payload or ValidationRunRequest()
    try:
        return ValidationApplicationService().run(
            report_id,
            selected_rule_keys=request.selected_rule_keys,
            reuse_existing=request.reuse_existing,
            include_llm=request.include_llm,
            source_validation_run_id=request.source_validation_run_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/validation/reuse-runs", response_model=list[ValidationReuseRunOption])
def list_validation_reuse_runs(
    report_id: int = Query(gt=0),
) -> list[ValidationReuseRunOption]:
    return ValidationApplicationService().reusable_runs(report_id)


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
    mode: Literal["completed_report_new"] = Query(default="completed_report_new"),
    base_report_id: int | None = Query(default=None, gt=0),
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
                import_mode=mode,
                base_report_id=base_report_id,
                validate_after_import=False,
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
