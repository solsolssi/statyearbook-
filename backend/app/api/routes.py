from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from io import BytesIO
import zipfile

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.models.report import (
    ReportDeleteResult,
    ReportOverviewPayload,
    ReportPayload,
    ReportProcessingJob,
    StatTable,
    TableDownloadCatalogItem,
    ValidationProfileApprovalRequest,
    ValidationProfileSummary,
    ValidationCatalogItem,
    ValidationReuseRunOption,
    ValidationRunRequest,
    ValidationRunResult,
    ValidationJob,
)
from app.models.source_statistics import (
    SourceDataImportResult,
    SourceStatisticDetail,
    SourceStatisticsOverview,
)
from app.models.report_updates import ReportComparisonSummary
from app.models.yearbook_edits import (
    StatisticCloneRequest,
    TableContentUpdateRequest,
    ReportEditAccess,
    ReportEditAuthenticationRequest,
    ReportEditPasswordRequest,
    TableEditSession,
)
from app.application.imports import ReportImportApplicationService
from app.application.report_queries import ReportQueryService
from app.application.validation_operations import ValidationApplicationService
from app.services.validation_job_service import ValidationJobService
from app.export.validation_workbooks import export_validation_workbooks
from app.services.report_service import get_report_service
from app.services.report_import_service import (
    ReportImportRequest,
    ReportUploadError,
)
from app.services.source_statistics_service import SourceStatisticsService
from app.services.incremental_yearbook_service import IncrementalYearbookService
from app.services.llm_assistance_service import ReportLLMAssistanceService
from app.services.report_update_service import ReportComparisonService
from app.services.yearbook_edit_service import (
    YearbookEditAuthenticationError,
    YearbookEditError,
    YearbookEditService,
)
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
    include_llm: bool = Query(default=False),
    info_file: UploadFile = File(),
    item_file: UploadFile = File(),
    value_file: UploadFile = File(),
) -> SourceDataImportResult:
    """Create an editable draft from one report-scoped increment upload."""
    with TemporaryDirectory() as directory:
        root = Path(directory)
        # The three system exports may share a generic filename.  Keep their
        # temporary paths distinct so one selected file can never overwrite
        # another before parsing.
        info_path = await save_uploaded_excel(info_file, root, "info")
        item_path = await save_uploaded_excel(item_file, root, "item")
        value_path = await save_uploaded_excel(value_file, root, "value")
        try:
            generated = IncrementalYearbookService().create_draft(
                base_report_id=base_report_id,
                target_year=target_year,
                title=title,
                info_path=info_path,
                item_path=item_path,
                value_path=value_path,
            )
            llm_assistance = (
                ReportLLMAssistanceService().assist_increment(generated.report_id)
                if include_llm
                else {}
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    return SourceDataImportResult(
        mode=mode,
        base_report_id=base_report_id,
        target_year=target_year,
        generated_report_id=generated.report_id,
        datasets=generated.datasets,
        items=generated.items,
        values=generated.values,
        inserted_values=generated.values,
        generated_table_count=generated.generated_table_count,
        review_table_count=generated.review_table_count,
        deleted_table_count=generated.deleted_table_count,
        new_table_count=generated.new_table_count,
        source_snapshot_id=0,
        llm_assistance=llm_assistance,
    )


@router.put("/reports/{report_id}/incremental-mappings/{table_code}")
def set_incremental_mapping(
    report_id: int,
    table_code: str,
    source_key: str = Query(min_length=1),
) -> dict[str, str | int | bool]:
    try:
        return IncrementalYearbookService().set_mapping(
            report_id=report_id,
            table_code=table_code,
            source_key=source_key,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/reports/{report_id}/incremental-mappings/{table_code}/preview")
def preview_incremental_mapping(
    report_id: int,
    table_code: str,
    source_key: str = Query(min_length=1),
) -> dict[str, object]:
    try:
        return IncrementalYearbookService().preview_mapping(
            report_id=report_id,
            table_code=table_code,
            source_key=source_key,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/reports/{report_id}/incremental-connections")
def list_incremental_connections(report_id: int) -> dict[str, object]:
    try:
        return IncrementalYearbookService().list_connections(report_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/reports/{report_id}/incremental-connections/{source_key}/create-statistic")
def create_statistic_from_increment(
    report_id: int,
    source_key: str,
    table_code: str = Query(min_length=1),
    title: str = Query(min_length=1),
) -> dict[str, object]:
    try:
        return IncrementalYearbookService().create_statistic_from_increment(
            report_id=report_id,
            source_key=source_key,
            table_code=table_code,
            title=title,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/reports/{report_id}/incremental-connections/{table_code}/keep-existing")
def keep_existing_increment_table(report_id: int, table_code: str) -> dict[str, object]:
    try:
        return IncrementalYearbookService().keep_existing_table(
            report_id=report_id,
            table_code=table_code,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/reports/{report_id}/incremental-connections/{source_key}/ignore")
def ignore_unmatched_increment(report_id: int, source_key: str) -> dict[str, object]:
    try:
        return IncrementalYearbookService().ignore_unmatched_increment(
            report_id=report_id,
            source_key=source_key,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/reports/{report_id}/confirm-increment")
def confirm_increment_report(report_id: int) -> dict[str, bool]:
    try:
        IncrementalYearbookService().confirm_draft(report_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"confirmed": True}


async def save_uploaded_excel(upload: UploadFile, directory: Path, role: str) -> Path:
    safe_name = Path(upload.filename or "").name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in {".xls", ".xlsx"}:
        raise HTTPException(status_code=415, detail=".xls, .xlsx 파일만 업로드할 수 있습니다.")
    destination = directory / f"{role}_{safe_name}"
    destination.write_bytes(await upload.read())
    return destination


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
    IncrementalYearbookService().refresh_automatic_mappings(report_id)
    return ReportQueryService(get_report_service()).legacy_payload(report_id)


@router.get("/report/overview", response_model=ReportOverviewPayload)
def get_report_overview(report_id: int | None = Query(default=None)) -> ReportOverviewPayload:
    IncrementalYearbookService().refresh_automatic_mappings(report_id)
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


@router.get(
    "/reports/{report_id}/table-download-catalog",
    response_model=list[TableDownloadCatalogItem],
)
def get_table_download_catalog(report_id: int) -> list[TableDownloadCatalogItem]:
    return ReportQueryService(get_report_service()).download_catalog(report_id)


@router.get("/tables/{table_id}", response_model=StatTable)
def get_table(table_id: str, report_id: int | None = Query(default=None)) -> StatTable:
    table = ReportQueryService(get_report_service()).table_detail(table_id, report_id)
    if table is None:
        raise HTTPException(status_code=404, detail="Table not found")
    return table


@router.get(
    "/reports/{report_id}/edit-access",
    response_model=ReportEditAccess,
)
def get_report_edit_access(report_id: int) -> ReportEditAccess:
    try:
        return YearbookEditService().get_access(report_id)
    except YearbookEditError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.put(
    "/reports/{report_id}/tables/{table_id}/edit-password",
    response_model=ReportEditAccess,
)
def set_report_edit_password(
    report_id: int,
    table_id: str,
    payload: ReportEditPasswordRequest,
) -> ReportEditAccess:
    try:
        return YearbookEditService().set_password(
            report_id=report_id,
            table_id=table_id,
            new_password=payload.new_password,
            current_password=payload.current_password,
        )
    except YearbookEditAuthenticationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except YearbookEditError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post(
    "/reports/{report_id}/tables/{table_id}/edit-session",
    response_model=TableEditSession,
)
def authenticate_table_edit(
    report_id: int,
    table_id: str,
    payload: ReportEditAuthenticationRequest,
) -> TableEditSession:
    try:
        return YearbookEditService().authenticate(
            report_id=report_id,
            table_id=table_id,
            password=payload.password,
        )
    except YearbookEditAuthenticationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except YearbookEditError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put(
    "/reports/{report_id}/tables/{table_id}",
    response_model=StatTable,
)
def update_table_content(
    report_id: int,
    table_id: str,
    payload: TableContentUpdateRequest,
    authorization: str | None = Header(default=None),
) -> StatTable:
    scheme, _, access_token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not access_token:
        raise HTTPException(status_code=401, detail="수정 비밀번호 인증이 필요합니다.")
    try:
        return YearbookEditService().update_table(
            report_id=report_id,
            table_id=table_id,
            access_token=access_token,
            payload=payload,
        )
    except YearbookEditAuthenticationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except YearbookEditError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post(
    "/reports/{report_id}/tables/{table_id}/clone",
    response_model=StatTable,
)
def clone_statistic(
    report_id: int,
    table_id: str,
    payload: StatisticCloneRequest,
    authorization: str | None = Header(default=None),
) -> StatTable:
    scheme, _, access_token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not access_token:
        raise HTTPException(status_code=401, detail="수정 비밀번호 인증이 필요합니다.")
    try:
        return YearbookEditService().clone_statistic(
            report_id=report_id,
            table_id=table_id,
            access_token=access_token,
            payload=payload,
        )
    except YearbookEditAuthenticationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except YearbookEditError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/reports/{report_id}/tables/{table_id}")
def delete_statistic(
    report_id: int,
    table_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, int]:
    scheme, _, access_token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not access_token:
        raise HTTPException(status_code=401, detail="수정 비밀번호 인증이 필요합니다.")
    try:
        return {
            "deleted_table_count": YearbookEditService().delete_statistic(
                report_id=report_id,
                table_id=table_id,
                access_token=access_token,
            )
        }
    except YearbookEditAuthenticationError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    except YearbookEditError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/validation/run", response_model=ValidationRunResult)
def run_validation(
    payload: ValidationRunRequest | None = None,
    report_id: int | None = Query(default=None),
) -> ValidationRunResult:
    request = payload or ValidationRunRequest()
    try:
        return ValidationApplicationService().run(
            report_id,
            selected_rule_keys=request.selected_rule_keys,
            reuse_existing=request.reuse_existing,
            include_profile_llm=(
                request.include_llm
                if request.include_profile_llm is None
                else request.include_profile_llm
            ),
            include_language_llm=(
                request.include_llm
                if request.include_language_llm is None
                else request.include_language_llm
            ),
            source_validation_run_id=request.source_validation_run_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/validation/jobs", response_model=ValidationJob, status_code=status.HTTP_202_ACCEPTED)
def create_validation_job(
    payload: ValidationRunRequest,
    background_tasks: BackgroundTasks,
    report_id: int = Query(gt=0),
) -> ValidationJob:
    options = {
        "selected_rule_keys": payload.selected_rule_keys,
        "reuse_existing": payload.reuse_existing,
        "include_profile_llm": payload.include_llm if payload.include_profile_llm is None else payload.include_profile_llm,
        "include_language_llm": payload.include_llm if payload.include_language_llm is None else payload.include_language_llm,
        "source_validation_run_id": payload.source_validation_run_id,
    }
    service = ValidationJobService()
    job = service.create(report_id, options)
    background_tasks.add_task(service.run, int(job["id"]))
    return ValidationJob(**job)


@router.get("/validation/jobs/{job_id}", response_model=ValidationJob)
def get_validation_job(job_id: int) -> ValidationJob:
    job = ValidationJobService().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="검수 작업을 찾을 수 없습니다.")
    return ValidationJob(**job)


@router.post("/validation/jobs/{job_id}/stop", response_model=ValidationJob)
def stop_validation_job(job_id: int) -> ValidationJob:
    job = ValidationJobService().request_stop(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="검수 작업을 찾을 수 없습니다.")
    return ValidationJob(**job)


@router.get("/validation/reuse-runs", response_model=list[ValidationReuseRunOption])
def list_validation_reuse_runs(
    report_id: int = Query(gt=0),
) -> list[ValidationReuseRunOption]:
    return ValidationApplicationService().reusable_runs(report_id)


@router.get("/reports/{report_id}/validation-report")
def download_validation_report(
    report_id: int,
    status_filter: list[str] | None = Query(default=None, alias="status"),
    component_filter: list[str] | None = Query(default=None, alias="component"),
) -> StreamingResponse:
    allowed_statuses = {"확인 필요", "오류 의심"}
    allowed_components = {"validation_index", "highlighted", "metadata"}
    selected_statuses = tuple(
        dict.fromkeys(value for value in (status_filter or []) if value in allowed_statuses)
    )
    if status_filter and not selected_statuses:
        raise HTTPException(status_code=400, detail="내보낼 검수 상태를 선택해 주세요.")
    selected_components = tuple(
        dict.fromkeys(value for value in (component_filter or []) if value in allowed_components)
    )
    if component_filter and not selected_components:
        raise HTTPException(status_code=400, detail="포함할 리포트 파일을 선택해 주세요.")
    if not selected_components:
        selected_components = ("validation_index", "highlighted", "metadata")
    try:
        with TemporaryDirectory() as directory:
            result = export_validation_workbooks(
                report_id=report_id,
                statuses=selected_statuses or ("오류 의심", "확인 필요"),
                output_dir=Path(directory),
            )
            archive = BytesIO()
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                component_paths = {
                    "metadata": result.metadata_path,
                    "highlighted": result.highlighted_path,
                    "validation_index": result.validation_index_path,
                }
                for component in selected_components:
                    path = component_paths[component]
                    bundle.write(path, arcname=path.name)
            archive.seek(0)
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    headers = {
        "Content-Disposition": f'attachment; filename="validation-report-{report_id}.zip"'
    }
    return StreamingResponse(archive, media_type="application/zip", headers=headers)


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
