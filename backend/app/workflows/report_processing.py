from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Callable

from app.db.connection import DB_PATH
from app.ingest.excel_importer import import_excel
from app.ingest.hwpx_importer import import_hwpx
from app.ingest.markdown_importer import import_markdown
from app.validation.calculation_workflow import CalculationValidationWorkflow
from app.validation.language_workflow import LanguageValidationWorkflow
from app.validation.repository import ValidationRepository
from app.validation.workflow import validation_issue_count
from app.workflows.report_job_repository import ReportProcessingJobRepository


SUPPORTED_SOURCE_TYPES = {
    ".xlsx": "xlsx",
    ".hwpx": "hwpx",
    ".md": "markdown",
}
SOURCE_IMPORTERS = {
    "xlsx": import_excel,
    "hwpx": import_hwpx,
    "markdown": import_markdown,
}


@dataclass(frozen=True)
class ReportProcessingOptions:
    include_llm: bool = False
    refresh_profiles: bool = False


class ReportProcessingError(RuntimeError):
    def __init__(self, job_id: int, stage: str, message: str) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.stage = stage


class ReportProcessingWorkflow:
    """Import and validate one uploaded report with persistent stage state."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        job_repository: ReportProcessingJobRepository | None = None,
    ) -> None:
        self._db_path = db_path
        self._jobs = job_repository or ReportProcessingJobRepository(db_path)

    def create_job(
        self,
        *,
        source_path: Path,
        year: int,
        title: str,
        options: ReportProcessingOptions | None = None,
        source_type: str | None = None,
    ) -> int:
        selected_source_type = source_type or SUPPORTED_SOURCE_TYPES.get(source_path.suffix.lower())
        if selected_source_type is None or selected_source_type not in SUPPORTED_SOURCE_TYPES.values():
            supported = ", ".join(sorted(SUPPORTED_SOURCE_TYPES))
            raise ValueError(f"지원하지 않는 파일 형식입니다. 지원 형식: {supported}")
        payload = options or ReportProcessingOptions()
        return self._jobs.create(
            source_file_name=source_path.name,
            source_file_path=str(source_path),
            source_type=selected_source_type,
            report_year=year,
            report_title=title,
            options=payload.__dict__,
        )

    def run(self, job_id: int) -> dict[str, object]:
        job = self.get_job(job_id)
        if job is None:
            raise ReportProcessingError(job_id, "queued", "가져오기 작업을 찾을 수 없습니다.")
        if job["status"] == "completed":
            return job

        # ``queue_retry`` changes only the status. Keeping the persisted stage
        # lets a retry resume after the last successful stage instead of
        # importing the same source a second time.
        resume_stage = str(job["current_stage"] or "import")
        self._jobs.update(
            job_id,
            status="running",
            current_stage=resume_stage,
            started=True,
            error="",
        )
        try:
            options = processing_options_from_json(str(job["options_json"] or "{}"))
            report_id = int(job["report_id"]) if job["report_id"] is not None else None
            run_id = int(job["run_id"]) if job["run_id"] is not None else None

            import_result = self._jobs.completed_stage_result(job_id, "import")
            if report_id is None or resume_stage == "import":
                import_result = self._run_stage(job_id, "import", lambda: self._import_source(job))
                report_id = int(import_result["report_id"])
                run_id = None
                self._jobs.update(
                    job_id,
                    report_id=report_id,
                    current_stage="calculation_validation",
                )

            calculation_result = self._jobs.completed_stage_result(
                job_id,
                "calculation_validation",
            )
            if run_id is None or resume_stage in {"import", "calculation_validation"}:
                calculation_result = self._run_stage(
                    job_id,
                    "calculation_validation",
                    lambda: asdict(
                        CalculationValidationWorkflow(self._db_path).run(
                            report_id=report_id,
                            refresh_profiles=options.refresh_profiles,
                        )
                    ),
                )
                run_id = int(calculation_result["run_id"])
                self._jobs.update(
                    job_id,
                    report_id=report_id,
                    run_id=run_id,
                    current_stage="language_validation",
                )

            report = ValidationRepository(self._db_path).report(report_id)
            if report is None:
                raise RuntimeError(f"검수할 연보를 찾을 수 없습니다: {report_id}")
            language_result = self._run_stage(
                job_id,
                "language_validation",
                lambda: self._run_language_validation(
                    report_id=report_id,
                    run_id=run_id,
                    source_path=str(report["source_file_path"]),
                    include_llm=options.include_llm,
                ),
            )
            result = {
                "import": import_result,
                "calculation_validation": calculation_result,
                "language_validation": language_result,
                "issues": validation_issue_count(self._db_path, run_id),
            }
            self._jobs.update(
                job_id,
                report_id=report_id,
                run_id=run_id,
                status="completed",
                current_stage="completed",
                result=result,
                completed=True,
            )
            return self.get_job(job_id) or result
        except ReportProcessingError:
            raise
        except Exception as error:
            stage = str((self.get_job(job_id) or {}).get("current_stage") or "unknown")
            self._jobs.update(
                job_id,
                status="failed",
                current_stage=stage,
                error=str(error),
                completed=True,
            )
            raise ReportProcessingError(job_id, stage, str(error)) from error

    def retry(self, job_id: int) -> dict[str, object]:
        job = self.get_job(job_id)
        if job is None:
            raise ReportProcessingError(job_id, "queued", "가져오기 작업을 찾을 수 없습니다.")
        if job["status"] not in {"failed", "queued"}:
            return job
        return self.run(job_id)

    def queue_retry(self, job_id: int) -> dict[str, object]:
        """Make a failed job observable as queued before a worker resumes it."""

        job = self.get_job(job_id)
        if job is None:
            raise ReportProcessingError(job_id, "queued", "가져오기 작업을 찾을 수 없습니다.")
        if job["status"] == "failed":
            self._jobs.update(job_id, status="queued", error="")
        return self.get_job(job_id) or job

    def get_job(self, job_id: int) -> dict[str, object] | None:
        return self._jobs.get(job_id)

    def _import_source(self, job: dict[str, object]) -> dict[str, int | str]:
        source_path = Path(str(job["source_file_path"]))
        common = {
            "db_path": self._db_path,
            "year": int(job["report_year"]),
            "title": str(job["report_title"]),
            "run_validation": False,
        }
        source_type = str(job["source_type"])
        importer = SOURCE_IMPORTERS.get(source_type)
        if importer is None:
            raise ValueError(f"등록되지 않은 가져오기 형식입니다: {source_type}")
        return importer(source_path, **common)

    def _run_language_validation(
        self,
        *,
        report_id: int,
        run_id: int,
        source_path: str,
        include_llm: bool,
    ) -> dict[str, object]:
        result = LanguageValidationWorkflow(self._db_path).run(
            report_id=report_id,
            run_id=run_id,
            source_path=source_path,
            include_llm=include_llm,
        )
        return {**asdict(result), "status": result.status}

    def _run_stage(
        self,
        job_id: int,
        stage_name: str,
        operation: Callable[[], dict[str, object] | dict[str, int | str]],
    ) -> dict[str, object]:
        attempt = self._jobs.start_stage(job_id, stage_name)
        self._jobs.update(job_id, current_stage=stage_name)
        try:
            result = dict(operation())
        except Exception as error:
            self._jobs.finish_stage(
                job_id,
                stage_name,
                attempt,
                status="failed",
                error=str(error),
            )
            self._jobs.update(
                job_id,
                status="failed",
                current_stage=stage_name,
                error=str(error),
                completed=True,
            )
            raise ReportProcessingError(job_id, stage_name, str(error)) from error
        self._jobs.finish_stage(
            job_id,
            stage_name,
            attempt,
            status="completed",
            result=result,
        )
        return result


def processing_options_from_json(value: str) -> ReportProcessingOptions:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return ReportProcessingOptions(
        include_llm=bool(payload.get("include_llm", False)),
        refresh_profiles=bool(payload.get("refresh_profiles", False)),
    )
