from __future__ import annotations

from datetime import datetime, timedelta
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
        source_storage: str = "local",
        source_object_key: str = "",
        source_file_hash: str = "",
        source_file_size: int = 0,
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
                    source_file_name, source_file_path, source_storage,
                    source_object_key, source_file_hash, source_file_size, source_type,
                    report_year, report_title, options_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_file_name,
                    source_file_path,
                    source_storage,
                    source_object_key,
                    source_file_hash,
                    source_file_size,
                    source_type,
                    report_year,
                    report_title,
                    json.dumps(options, ensure_ascii=False, sort_keys=True),
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def find_reusable(
        self,
        *,
        source_file_hash: str,
        report_year: int,
        report_title: str,
        options: dict[str, object],
    ) -> dict[str, object] | None:
        options_json = json.dumps(options, ensure_ascii=False, sort_keys=True)
        with connect(self._db_path) as connection:
            init_db(connection)
            row = connection.execute(
                """
                SELECT id
                FROM report_processing_jobs
                WHERE source_file_hash = ? AND report_year = ? AND report_title = ?
                  AND options_json = ?
                  AND status IN ('queued', 'running', 'completed')
                ORDER BY id DESC
                LIMIT 1
                """,
                (source_file_hash, report_year, report_title, options_json),
            ).fetchone()
        return self.get(int(row["id"])) if row is not None else None

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
        progress_percent: int | None = None,
    ) -> None:
        assignments = ["updated_at = ?"]
        values: list[object] = [timestamp()]
        for column, value in (
            ("report_id", report_id),
            ("run_id", run_id),
            ("status", status),
            ("current_stage", current_stage),
            ("error_message", error),
            ("progress_percent", progress_percent),
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

    def acquire_lease(
        self,
        job_id: int,
        *,
        owner: str,
        lease_seconds: int,
    ) -> bool:
        now = datetime.now()
        expires_at = now + timedelta(seconds=max(lease_seconds, 1))
        with connect(self._db_path) as connection:
            init_db(connection)
            cursor = connection.execute(
                """
                UPDATE report_processing_jobs
                SET lease_owner = ?, lease_expires_at = ?, last_heartbeat_at = ?,
                    attempt_count = attempt_count + 1, updated_at = ?
                WHERE id = ? AND status <> 'completed'
                  AND (
                    lease_owner = ''
                    OR lease_owner = ?
                    OR lease_expires_at IS NULL
                    OR lease_expires_at < ?
                  )
                """,
                (
                    owner,
                    timestamp(expires_at),
                    timestamp(now),
                    timestamp(now),
                    job_id,
                    owner,
                    timestamp(now),
                ),
            )
            connection.commit()
            return int(cursor.rowcount or 0) == 1

    def heartbeat(
        self,
        job_id: int,
        *,
        owner: str,
        lease_seconds: int,
        progress_percent: int | None = None,
    ) -> bool:
        now = datetime.now()
        assignments = [
            "lease_expires_at = ?",
            "last_heartbeat_at = ?",
            "updated_at = ?",
        ]
        values: list[object] = [
            timestamp(now + timedelta(seconds=max(lease_seconds, 1))),
            timestamp(now),
            timestamp(now),
        ]
        if progress_percent is not None:
            assignments.append("progress_percent = ?")
            values.append(max(0, min(progress_percent, 100)))
        values.extend((job_id, owner))
        with connect(self._db_path) as connection:
            init_db(connection)
            cursor = connection.execute(
                f"""
                UPDATE report_processing_jobs
                SET {', '.join(assignments)}
                WHERE id = ? AND lease_owner = ?
                """,
                values,
            )
            connection.commit()
            return int(cursor.rowcount or 0) == 1

    def release_lease(self, job_id: int, *, owner: str) -> None:
        with connect(self._db_path) as connection:
            init_db(connection)
            connection.execute(
                """
                UPDATE report_processing_jobs
                SET lease_owner = '', lease_expires_at = NULL,
                    last_heartbeat_at = ?, updated_at = ?
                WHERE id = ? AND lease_owner = ?
                """,
                (timestamp(), timestamp(), job_id, owner),
            )
            connection.commit()

    def next_claimable_job_id(self) -> int | None:
        now = timestamp()
        with connect(self._db_path) as connection:
            init_db(connection)
            row = connection.execute(
                """
                SELECT id
                FROM report_processing_jobs
                WHERE status IN ('queued', 'running')
                  AND (
                    lease_owner = ''
                    OR lease_expires_at IS NULL
                    OR lease_expires_at < ?
                  )
                ORDER BY
                    CASE status WHEN 'running' THEN 0 ELSE 1 END,
                    updated_at,
                    id
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            return int(row["id"]) if row is not None else None

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


def timestamp(value: datetime | None = None) -> str:
    return (value or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


def json_object(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}
