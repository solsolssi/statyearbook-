from __future__ import annotations

from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from uuid import uuid4

from app.core.config import Settings, get_settings
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


class LocalUploadStore:
    """Store an upload while enforcing the configured size limit."""

    def __init__(self, upload_dir: Path, max_bytes: int) -> None:
        self._upload_dir = upload_dir
        self._max_bytes = max_bytes

    async def save(self, filename: str, chunks: AsyncIterable[bytes]) -> Path:
        safe_name = validated_filename(filename)
        self._upload_dir.mkdir(parents=True, exist_ok=True)
        destination = self._upload_dir / f"{uuid4().hex}_{safe_name}"
        bytes_written = 0

        try:
            with destination.open("wb") as output:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    bytes_written += len(chunk)
                    if bytes_written > self._max_bytes:
                        raise ReportUploadError(
                            "업로드 가능한 파일 크기를 초과했습니다.",
                            status_code=413,
                        )
                    output.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise

        if bytes_written == 0:
            destination.unlink(missing_ok=True)
            raise ReportUploadError("업로드 파일이 비어 있습니다.")
        return destination


class ReportImportService:
    """Persist one upload and create its database-backed processing job."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        workflow: ReportProcessingWorkflow | None = None,
        upload_store: LocalUploadStore | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._workflow = workflow or ReportProcessingWorkflow()
        self._upload_store = upload_store or LocalUploadStore(
            self._settings.upload_dir,
            self._settings.max_upload_bytes,
        )

    async def create_job(
        self,
        request: ReportImportRequest,
        chunks: AsyncIterable[bytes],
    ) -> dict[str, object]:
        source_path = await self._upload_store.save(request.filename, chunks)
        report_year = request.year or infer_report_year(request.filename)

        try:
            job_id = self._workflow.create_job(
                source_path=source_path,
                year=report_year,
                title=request.title or f"{report_year} 행정안전통계연보",
                options=ReportProcessingOptions(
                    include_llm=(
                        self._settings.auto_import_include_llm
                        if request.include_llm is None
                        else request.include_llm
                    ),
                    refresh_profiles=request.refresh_profiles,
                ),
            )
        except Exception:
            source_path.unlink(missing_ok=True)
            raise

        job = self._workflow.get_job(job_id)
        if job is None:
            raise RuntimeError(f"생성한 가져오기 작업을 찾을 수 없습니다: {job_id}")
        return job


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
