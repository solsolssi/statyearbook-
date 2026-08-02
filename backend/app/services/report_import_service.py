from __future__ import annotations

from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from app.core.config import Settings, get_settings
from app.ingest.repository import file_digest
from app.storage.source_storage import (
    LocalSourceStorage,
    SourceStorage,
    SourceStorageError,
    StoredSource,
    source_storage_from_settings,
)
from app.workflows.report_processing import (
    ReportProcessingOptions,
    ReportProcessingWorkflow,
)


ALLOWED_UPLOAD_SUFFIXES = {".xlsx", ".hwpx", ".md"}


class ReportUploadError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ReportImportRequest:
    filename: str
    year: int | None = None
    title: str | None = None
    include_llm: bool | None = None
    refresh_profiles: bool = False
    import_mode: str = "completed_report_new"
    base_report_id: int | None = None
    validate_after_import: bool = True


class LocalUploadStore:
    """Backward-compatible adapter around the local SourceStorage."""

    def __init__(self, upload_dir: Path, max_bytes: int) -> None:
        self._storage = LocalSourceStorage(upload_dir)
        self._max_bytes = max_bytes

    async def save(self, filename: str, chunks: AsyncIterable[bytes]) -> Path:
        safe_name = validated_filename(filename)
        try:
            stored = await self._storage.save(
                safe_name,
                chunks,
                max_bytes=self._max_bytes,
            )
        except SourceStorageError as error:
            raise upload_error_from_storage(error) from error
        if stored.local_path is None:
            raise RuntimeError("로컬 업로드 파일 경로가 생성되지 않았습니다.")
        return stored.local_path


class ReportImportService:
    """Persist one upload and create its database-backed processing job."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        workflow: ReportProcessingWorkflow | None = None,
        upload_store: LocalUploadStore | None = None,
        source_storage: SourceStorage | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._workflow = workflow or ReportProcessingWorkflow(settings=self._settings)
        self._upload_store = upload_store
        self._source_storage = source_storage or source_storage_from_settings(self._settings)

    async def create_job(
        self,
        request: ReportImportRequest,
        chunks: AsyncIterable[bytes],
    ) -> dict[str, object]:
        safe_name = validated_filename(request.filename)
        if self._upload_store is not None:
            source_path = await self._upload_store.save(safe_name, chunks)
            stored_source = stored_source_from_local_path(source_path, filename=safe_name)
        else:
            try:
                stored_source = await self._source_storage.save(
                    safe_name,
                    chunks,
                    max_bytes=self._settings.max_upload_bytes,
                )
            except SourceStorageError as error:
                raise upload_error_from_storage(error) from error
        report_year = request.year or infer_report_year(request.filename)
        report_title = request.title or f"{report_year} 행정안전통계연보"
        options = ReportProcessingOptions(
            include_llm=(
                self._settings.auto_import_include_llm
                if request.include_llm is None
                else request.include_llm
            ),
            refresh_profiles=request.refresh_profiles,
            import_mode=request.import_mode,
            base_report_id=request.base_report_id,
            validate_after_import=request.validate_after_import,
        )

        try:
            reusable = self._workflow.find_reusable_job(
                source_file_hash=stored_source.sha256,
                year=report_year,
                title=report_title,
                options=options,
            )
            if reusable is not None:
                existing_key = str(reusable.get("source_object_key") or "")
                if stored_source.object_key != existing_key:
                    self._delete_stored_source(stored_source)
                return reusable
            job_id = self._workflow.create_job(
                source_path=stored_source.local_path or Path(stored_source.filename),
                year=report_year,
                title=report_title,
                options=options,
                stored_source=stored_source,
            )
        except Exception:
            self._delete_stored_source(stored_source)
            raise

        job = self._workflow.get_job(job_id)
        if job is None:
            raise RuntimeError(f"생성한 가져오기 작업을 찾을 수 없습니다: {job_id}")
        return job

    def _delete_stored_source(self, source: StoredSource) -> None:
        if source.storage_kind == "local":
            Path(source.object_key).unlink(missing_ok=True)
            return
        self._source_storage.delete(source.object_key)


def validated_filename(filename: str) -> str:
    safe_name = Path(filename).name
    suffix = Path(safe_name).suffix.lower()
    if not safe_name or suffix not in ALLOWED_UPLOAD_SUFFIXES:
        supported = ", ".join(sorted(ALLOWED_UPLOAD_SUFFIXES))
        raise ReportUploadError(
            f"{supported} 파일만 업로드할 수 있습니다.",
            status_code=415,
        )
    return safe_name


def infer_report_year(filename: str, *, fallback_year: int | None = None) -> int:
    match = re.search(r"(?:19|20)\d{2}", Path(filename).name)
    if match:
        return int(match.group(0))
    return fallback_year or datetime.now().year


def stored_source_from_local_path(path: Path, *, filename: str) -> StoredSource:
    return StoredSource(
        storage_kind="local",
        object_key=str(path),
        filename=filename,
        size=path.stat().st_size,
        sha256=file_digest(path),
        local_path=path,
    )


def upload_error_from_storage(error: SourceStorageError) -> ReportUploadError:
    message = str(error)
    return ReportUploadError(
        message,
        status_code=413 if "크기" in message else 400,
    )
