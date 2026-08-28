from __future__ import annotations

import json
from pathlib import Path

from app.db.connection import DB_PATH, connect
from app.db.schema import init_db
from app.services.validation_execution_service import ValidationExecutionService


class ValidationJobService:
    """Persisted, resumable shell around a validation execution."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def create(self, report_id: int, options: dict[str, object]) -> dict[str, object]:
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                cursor = connection.execute(
                    """
                    INSERT INTO validation_jobs (report_id, options_json)
                    VALUES (?, ?)
                    """,
                    (report_id, json.dumps(options, ensure_ascii=False)),
                )
                job_id = int(cursor.lastrowid or 0)
        return self.get(job_id) or {}

    def get(self, job_id: int) -> dict[str, object] | None:
        with connect(self._db_path) as connection:
            init_db(connection)
            row = connection.execute("SELECT * FROM validation_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        try:
            result = json.loads(str(row["result_json"] or "{}"))
        except json.JSONDecodeError:
            result = {}
        return {
            "id": int(row["id"]), "report_id": int(row["report_id"]),
            "status": str(row["status"]), "current_stage": str(row["current_stage"]),
            "progress_percent": int(row["progress_percent"] or 0),
            "completed_units": int(row["completed_units"] or 0),
            "total_units": int(row["total_units"] or 0),
            "cancel_requested": bool(row["cancel_requested"]),
            "result": result or None, "error_message": str(row["error_message"] or ""),
            "created_at": str(row["created_at"]), "started_at": row["started_at"],
            "completed_at": row["completed_at"],
        }

    def request_stop(self, job_id: int) -> dict[str, object] | None:
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                connection.execute(
                    """UPDATE validation_jobs SET cancel_requested = 1,
                       current_stage = '중단 요청됨', updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND status IN ('queued', 'running')""",
                    (job_id,),
                )
        return self.get(job_id)

    def run(self, job_id: int) -> None:
        job = self.get(job_id)
        if not job:
            return
        options = self._options(job_id)
        self._update(job_id, status="running", stage="검수 준비", progress=5)
        if self._should_stop(job_id):
            self._stop(job_id)
            return
        try:
            result = ValidationExecutionService(self._db_path).run(
                report_id=int(job["report_id"]),
                selected_rule_keys=list(options.get("selected_rule_keys") or []),
                reuse_existing=bool(options.get("reuse_existing", True)),
                include_profile_llm=bool(options.get("include_profile_llm", False)),
                include_language_llm=bool(options.get("include_language_llm", False)),
                source_validation_run_id=(int(options["source_validation_run_id"])
                                          if options.get("source_validation_run_id") else None),
                on_progress=lambda stage, done, total, percent: self._update(
                    job_id, stage=stage, completed=done, total=total, progress=percent
                ),
                should_stop=lambda: self._should_stop(job_id),
            )
            if bool(result.get("cancelled")) or self._should_stop(job_id):
                self._stop(job_id, result)
            else:
                self._complete(job_id, result)
        except Exception as error:
            self._update(job_id, status="failed", stage="검수 실패", error=str(error)[:1000], completed_at=True)

    def _options(self, job_id: int) -> dict[str, object]:
        with connect(self._db_path) as connection:
            row = connection.execute("SELECT options_json FROM validation_jobs WHERE id = ?", (job_id,)).fetchone()
        try:
            return json.loads(str(row["options_json"] or "{}")) if row else {}
        except json.JSONDecodeError:
            return {}

    def _should_stop(self, job_id: int) -> bool:
        with connect(self._db_path) as connection:
            row = connection.execute("SELECT cancel_requested FROM validation_jobs WHERE id = ?", (job_id,)).fetchone()
        return bool(row and row["cancel_requested"])

    def _update(self, job_id: int, *, status: str | None = None, stage: str | None = None,
                progress: int | None = None, completed: int | None = None, total: int | None = None,
                error: str | None = None, completed_at: bool = False) -> None:
        fields, values = ["updated_at = CURRENT_TIMESTAMP"], []
        for key, value in (("status", status), ("current_stage", stage), ("progress_percent", progress),
                           ("completed_units", completed), ("total_units", total), ("error_message", error)):
            if value is not None:
                fields.append(f"{key} = ?"); values.append(value)
        if status == "running": fields.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
        if completed_at: fields.append("completed_at = CURRENT_TIMESTAMP")
        values.append(job_id)
        with connect(self._db_path) as connection:
            with connection:
                connection.execute(f"UPDATE validation_jobs SET {', '.join(fields)} WHERE id = ?", values)

    def _complete(self, job_id: int, result: dict[str, object]) -> None:
        self._save_terminal(job_id, "completed", "검수 완료", 100, result)

    def _stop(self, job_id: int, result: dict[str, object] | None = None) -> None:
        self._save_terminal(job_id, "stopped", "중단됨 — 완료된 검수 결과 저장", None, result or {})

    def _save_terminal(self, job_id: int, status: str, stage: str, progress: int | None, result: dict[str, object]) -> None:
        with connect(self._db_path) as connection:
            with connection:
                connection.execute(
                    """UPDATE validation_jobs SET status=?, current_stage=?, progress_percent=COALESCE(?, progress_percent),
                       result_json=?, completed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (status, stage, progress, json.dumps(result, ensure_ascii=False), job_id),
                )
