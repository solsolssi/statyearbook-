from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import socket
from threading import Event, Thread
from typing import Callable
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.db.connection import DB_PATH
from app.ingest.parser_registry import parse_report
from app.ingest.repository import ReportImportRepository, file_digest
from app.storage.source_storage import StoredSource, source_storage_from_settings
from app.validation.calculation_workflow import CalculationValidationWorkflow
from app.validation.language_workflow import LanguageValidationWorkflow
from app.validation.repository import ValidationRepository
from app.validation.workflow import validation_issue_count
from app.services.report_update_service import ReportUpdateService
from app.workflows.report_job_repository import ReportProcessingJobRepository


SUPPORTED_SOURCE_TYPES = {
    ".xlsx": "xlsx",
    ".hwpx": "hwpx",
    ".md": "markdown",
}
@dataclass(frozen=True)
class ReportProcessingOptions:
    include_llm: bool = False
    refresh_profiles: bool = False
    import_mode: str = "completed_report_new"
    base_report_id: int | None = None
    validate_after_import: bool = True


class ReportProcessingError(RuntimeError):
    def __init__(self, job_id: int, stage: str, message: str) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.stage = stage


class ReportProcessingWorkflow:
    """Import a report and optionally run the legacy automatic validation stages."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        job_repository: ReportProcessingJobRepository | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._db_path = db_path
        self._jobs = job_repository or ReportProcessingJobRepository(db_path)
        self._settings = settings or get_settings()

    def create_job(
        self,
        *,
        source_path: Path,
        year: int,
        title: str,
        options: ReportProcessingOptions | None = None,
        source_type: str | None = None,
        stored_source: StoredSource | None = None,
    ) -> int:
        selected_source_type = source_type or SUPPORTED_SOURCE_TYPES.get(source_path.suffix.lower())
        if selected_source_type is None or selected_source_type not in SUPPORTED_SOURCE_TYPES.values():
            supported = ", ".join(sorted(SUPPORTED_SOURCE_TYPES))
            raise ValueError(f"지원하지 않는 파일 형식입니다. 지원 형식: {supported}")
        payload = options or ReportProcessingOptions()
        source = stored_source or StoredSource(
            storage_kind="local",
            object_key=str(source_path),
            filename=source_path.name,
            size=source_path.stat().st_size,
            sha256=file_digest(source_path),
            local_path=source_path,
        )
        return self._jobs.create(
            source_file_name=source.filename,
            source_file_path=source.persisted_path,
            source_storage=source.storage_kind,
            source_object_key=source.object_key,
            source_file_hash=source.sha256,
            source_file_size=source.size,
            source_type=selected_source_type,
            report_year=year,
            report_title=title,
            options=payload.__dict__,
        )

    def find_reusable_job(
        self,
        *,
        source_file_hash: str,
        year: int,
        title: str,
        options: ReportProcessingOptions,
    ) -> dict[str, object] | None:
        return self._jobs.find_reusable(
            source_file_hash=source_file_hash,
            report_year=year,
            report_title=title,
            options=options.__dict__,
        )

    def run(
        self,
        job_id: int,
        *,
        lease_owner: str | None = None,
    ) -> dict[str, object]:
        job = self.get_job(job_id)
        if job is None:
            raise ReportProcessingError(job_id, "queued", "가져오기 작업을 찾을 수 없습니다.")
        if job["status"] == "completed":
            return job
        owner = lease_owner or f"{socket.gethostname()}-{uuid4().hex[:8]}"
        if not self._jobs.acquire_lease(
            job_id,
            owner=owner,
            lease_seconds=self._settings.job_lease_seconds,
        ):
            raise ReportProcessingError(
                job_id,
                str(job.get("current_stage") or "queued"),
                "다른 작업자가 이미 이 가져오기 작업을 처리하고 있습니다.",
            )

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
            progress_percent=1,
        )
        keepalive = LeaseKeepalive(
            jobs=self._jobs,
            job_id=job_id,
            owner=owner,
            lease_seconds=self._settings.job_lease_seconds,
        )
        keepalive.start()
        try:
            options = processing_options_from_json(str(job["options_json"] or "{}"))
            report_id = int(job["report_id"]) if job["report_id"] is not None else None
            run_id = int(job["run_id"]) if job["run_id"] is not None else None

            import_result = self._jobs.completed_stage_result(job_id, "import")
            if report_id is None and import_result.get("report_id") is not None:
                report_id = int(import_result["report_id"])
            if report_id is None:
                import_result = self._run_stage(job_id, "import", lambda: self._import_source(job))
                report_id = int(import_result["report_id"])
                run_id = None
            partial_update = bool(import_result.get("update_batch_id"))
            changed_table_ids = [
                int(value)
                for value in import_result.get("changed_table_ids", [])
            ]
            if not options.validate_after_import:
                result = {"import": import_result}
                self._jobs.update(
                    job_id,
                    report_id=report_id,
                    run_id=None,
                    status="completed",
                    current_stage="completed",
                    result=result,
                    completed=True,
                    progress_percent=100,
                )
                return self.get_job(job_id) or result
            self._jobs.update(
                job_id,
                report_id=report_id,
                current_stage="calculation_validation",
                progress_percent=35,
            )
            self._heartbeat(job_id, owner, 35)

            calculation_result = self._jobs.completed_stage_result(
                job_id,
                "calculation_validation",
            )
            if run_id is None and calculation_result.get("run_id") is not None:
                run_id = int(calculation_result["run_id"])
            if run_id is None:
                calculation_result = self._run_stage(
                    job_id,
                    "calculation_validation",
                    lambda: asdict(
                        CalculationValidationWorkflow(self._db_path).run(
                            report_id=report_id,
                            refresh_profiles=options.refresh_profiles,
                            table_ids=changed_table_ids if partial_update else None,
                        )
                    ),
                )
                run_id = int(calculation_result["run_id"])
                if partial_update:
                    calculation_result["reused_check_count"] = ReportUpdateService(
                        self._db_path
                    ).reuse_unchanged_validation(
                        batch_id=int(import_result["update_batch_id"]),
                        new_run_id=run_id,
                    )
            self._jobs.update(
                job_id,
                report_id=report_id,
                run_id=run_id,
                current_stage="language_validation",
                progress_percent=70,
            )
            self._heartbeat(job_id, owner, 70)

            report = ValidationRepository(self._db_path).report(report_id)
            if report is None:
                raise RuntimeError(f"검수할 연보를 찾을 수 없습니다: {report_id}")
            language_result = self._jobs.completed_stage_result(
                job_id,
                "language_validation",
            )
            if not language_result:
                with self._materialize_source(job) as materialized_path:
                    language_result = self._run_stage(
                        job_id,
                        "language_validation",
                        lambda: self._run_language_validation(
                            report_id=report_id,
                            run_id=run_id,
                            source_path=str(materialized_path),
                            include_llm=options.include_llm,
                            table_ids=changed_table_ids if partial_update else None,
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
                progress_percent=100,
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
        finally:
            keepalive.stop()
            self._jobs.release_lease(job_id, owner=owner)

    def retry(
        self,
        job_id: int,
        *,
        lease_owner: str | None = None,
    ) -> dict[str, object]:
        job = self.get_job(job_id)
        if job is None:
            raise ReportProcessingError(job_id, "queued", "가져오기 작업을 찾을 수 없습니다.")
        if job["status"] not in {"failed", "queued"}:
            return job
        return self.run(job_id, lease_owner=lease_owner)

    def queue_retry(self, job_id: int) -> dict[str, object]:
        """Make a failed job observable as queued before a worker resumes it."""

        job = self.get_job(job_id)
        if job is None:
            raise ReportProcessingError(job_id, "queued", "가져오기 작업을 찾을 수 없습니다.")
        if job["status"] == "failed":
            self._jobs.update(job_id, status="queued", error="", progress_percent=0)
        return self.get_job(job_id) or job

    def get_job(self, job_id: int) -> dict[str, object] | None:
        return self._jobs.get(job_id)

    def _import_source(self, job: dict[str, object]) -> dict[str, object]:
        options = processing_options_from_json(str(job.get("options_json") or "{}"))
        with self._materialize_source(job) as source_path:
            report = parse_report(
                source_path,
                source_type=str(job["source_type"]),
                year=int(job["report_year"]),
                title=str(job["report_title"]),
                source_file_name=str(job["source_file_name"]),
                file_hash=str(job.get("source_file_hash") or ""),
            )
            imported = ReportImportRepository(self._db_path).replace_parsed_report(
                report,
                persisted_source_path=str(job["source_file_path"]),
                force_new=True,
                origin_kind=(
                    "uploaded_update"
                    if options.import_mode == "completed_report_update"
                    else "uploaded"
                ),
                base_report_id=options.base_report_id,
            )
            update = None
            if options.import_mode == "completed_report_update":
                if options.base_report_id is None:
                    raise ValueError("수정 연보 업로드에는 기준 연보가 필요합니다.")
                update = ReportUpdateService(self._db_path).record_update(
                    base_report_id=options.base_report_id,
                    report_id=imported.report_id,
                )
        result: dict[str, object] = {
            "db_path": str(self._db_path),
            "source_file": str(job["source_file_path"]),
            "report_id": imported.report_id,
            "tables": imported.table_count,
            "cells": imported.cell_count,
            "validation_issues": 0,
        }
        if update is not None:
            result.update(
                {
                    "update_batch_id": update.batch_id,
                    "changed_table_ids": update.changed_table_ids,
                    "changed_table_count": update.changed_table_count,
                    "unchanged_table_count": update.unchanged_table_count,
                    "added_table_count": update.added_table_count,
                    "deleted_table_count": update.deleted_table_count,
                    "changed_cell_count": update.changed_cell_count,
                }
            )
        return result

    def _materialize_source(self, job: dict[str, object]):  # type: ignore[no-untyped-def]
        storage_kind = str(job.get("source_storage") or "local")
        storage = source_storage_from_settings(
            self._settings,
            storage_kind=storage_kind,
        )
        object_key = str(
            job.get("source_object_key")
            or job.get("source_file_path")
            or ""
        )
        return storage.materialize(object_key, str(job["source_file_name"]))

    def _heartbeat(self, job_id: int, owner: str, progress_percent: int) -> None:
        if not self._jobs.heartbeat(
            job_id,
            owner=owner,
            lease_seconds=self._settings.job_lease_seconds,
            progress_percent=progress_percent,
        ):
            raise ReportProcessingError(
                job_id,
                "lease",
                "가져오기 작업 lease가 만료되어 처리를 중단했습니다.",
            )

    def _run_language_validation(
        self,
        *,
        report_id: int,
        run_id: int,
        source_path: str,
        include_llm: bool,
        table_ids: list[int] | None = None,
    ) -> dict[str, object]:
        result = LanguageValidationWorkflow(self._db_path).run(
            report_id=report_id,
            run_id=run_id,
            source_path=source_path,
            include_llm=include_llm,
            table_ids=table_ids,
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
        import_mode=str(payload.get("import_mode") or "completed_report_new"),
        base_report_id=(
            int(payload["base_report_id"])
            if payload.get("base_report_id") is not None
            else None
        ),
        validate_after_import=bool(payload.get("validate_after_import", True)),
    )


class LeaseKeepalive:
    def __init__(
        self,
        *,
        jobs: ReportProcessingJobRepository,
        job_id: int,
        owner: str,
        lease_seconds: int,
    ) -> None:
        self._jobs = jobs
        self._job_id = job_id
        self._owner = owner
        self._lease_seconds = max(lease_seconds, 3)
        self._stopped = Event()
        self._thread = Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        self._thread.join(timeout=1)

    def _run(self) -> None:
        interval = max(self._lease_seconds / 3, 1)
        while not self._stopped.wait(interval):
            try:
                self._jobs.heartbeat(
                    self._job_id,
                    owner=self._owner,
                    lease_seconds=self._lease_seconds,
                )
            except Exception:
                # Stage-boundary heartbeats surface a lost lease to the main
                # workflow. A transient keepalive failure should not kill the
                # worker thread or hide the actual validation error.
                continue
