from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from app.db.connection import DB_PATH, connect
from app.db.schema import init_db


class ReportProcessingJobRepository:
    """Persist report processing jobs and their stage attempts."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def create(
        self,
        *,
        source_file_name: str,
        source_file_path: str,
        source_type: str,
        report_year: int,
        report_title: str,
        options: dict[str, object],
    ) -> int:
        with connect(self._db_path) as connection:
            init_db(connection)
            cursor = connection.execute(
                """
                INSERT INTO report_processing_jobs (
                    source_file_name, source_file_path, source_type,
                    report_year, report_title, options_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source_file_name,
                    source_file_path,
                    source_type,
                    report_year,
                    report_title,
                    json.dumps(options, ensure_ascii=False),
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def get(self, job_id: int) -> dict[str, object] | None:
        with connect(self._db_path) as connection:
            init_db(connection)
            row = connection.execute(
                "SELECT * FROM report_processing_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            stages = connection.execute(
                """
                SELECT stage_name, attempt, status, result_json, error_message,
                       started_at, completed_at
                FROM report_processing_stages
                WHERE job_id = ?
                ORDER BY id
                """,
                (job_id,),
            ).fetchall()
            result = dict(row)
            result["stages"] = [dict(stage) for stage in stages]
            return result

    def update(
        self,
        job_id: int,
        *,
        report_id: int | None = None,
        run_id: int | None = None,
        status: str | None = None,
        current_stage: str | None = None,
        error: str | None = None,
        result: dict[str, object] | None = None,
        started: bool = False,
        completed: bool = False,
    ) -> None:
        assignments = ["updated_at = ?"]
        values: list[object] = [timestamp()]
        for column, value in (
            ("report_id", report_id),
            ("run_id", run_id),
            ("status", status),
            ("current_stage", current_stage),
            ("error_message", error),
        ):
            if value is not None:
                assignments.append(f"{column} = ?")
                values.append(value)
        if result is not None:
            assignments.append("result_json = ?")
            values.append(json.dumps(result, ensure_ascii=False))
        if started:
            assignments.append("started_at = COALESCE(started_at, ?)")
            values.append(timestamp())
        if completed:
            assignments.append("completed_at = ?")
            values.append(timestamp())
        values.append(job_id)

        with connect(self._db_path) as connection:
            init_db(connection)
            connection.execute(
                f"UPDATE report_processing_jobs SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            connection.commit()

    def start_stage(self, job_id: int, stage_name: str) -> int:
        with connect(self._db_path) as connection:
            init_db(connection)
            row = connection.execute(
                """
                SELECT COALESCE(MAX(attempt), 0) + 1 AS next_attempt
                FROM report_processing_stages
                WHERE job_id = ? AND stage_name = ?
                """,
                (job_id, stage_name),
            ).fetchone()
            attempt = int(row["next_attempt"])
            connection.execute(
                """
                INSERT INTO report_processing_stages (job_id, stage_name, attempt)
                VALUES (?, ?, ?)
                """,
                (job_id, stage_name, attempt),
            )
            connection.commit()
            return attempt

    def completed_stage_result(self, job_id: int, stage_name: str) -> dict[str, object]:
        with connect(self._db_path) as connection:
            init_db(connection)
            row = connection.execute(
                """
                SELECT result_json
                FROM report_processing_stages
                WHERE job_id = ? AND stage_name = ? AND status = 'completed'
                ORDER BY attempt DESC
                LIMIT 1
                """,
                (job_id, stage_name),
            ).fetchone()
            if row is None:
                return {}
            return json_object(str(row["result_json"] or "{}"))

    def finish_stage(
        self,
        job_id: int,
        stage_name: str,
        attempt: int,
        *,
        status: str,
        result: dict[str, object] | None = None,
        error: str = "",
    ) -> None:
        with connect(self._db_path) as connection:
            init_db(connection)
            connection.execute(
                """
                UPDATE report_processing_stages
                SET status = ?, result_json = ?, error_message = ?, completed_at = ?
                WHERE job_id = ? AND stage_name = ? AND attempt = ?
                """,
                (
                    status,
                    json.dumps(result or {}, ensure_ascii=False),
                    error,
                    timestamp(),
                    job_id,
                    stage_name,
                    attempt,
                ),
            )
            connection.commit()


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def json_object(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
