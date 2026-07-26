from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app.core.config import Settings, get_settings
from app.db.connection import DB_PATH, DatabaseRow, connect
from app.db.schema import init_db
from app.storage.source_storage import SourceStorage, source_storage_from_settings


StorageFactory = Callable[[Settings, str], SourceStorage]


@dataclass(frozen=True)
class RetentionResult:
    candidates: int
    deleted: int
    failed: int
    dry_run: bool
    errors: tuple[str, ...] = ()


class SourceRetentionService:
    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        settings: Settings | None = None,
        storage_factory: StorageFactory | None = None,
    ) -> None:
        self._db_path = db_path
        self._settings = settings or get_settings()
        self._storage_factory = storage_factory or default_storage_factory

    def prune(self, *, dry_run: bool = True) -> RetentionResult:
        candidates = self._expired_sources()
        if dry_run:
            return RetentionResult(
                candidates=len(candidates),
                deleted=0,
                failed=0,
                dry_run=True,
            )

        deleted = 0
        errors: list[str] = []
        for row in candidates:
            job_id = int(row["id"])
            storage_kind = str(row["source_storage"])
            object_key = str(row["source_object_key"] or row["source_file_path"] or "")
            try:
                storage = self._storage_factory(self._settings, storage_kind)
                storage.delete(object_key)
                self._mark_deleted(row)
                deleted += 1
            except Exception as error:
                errors.append(f"job {job_id}: {error}")
        return RetentionResult(
            candidates=len(candidates),
            deleted=deleted,
            failed=len(errors),
            dry_run=False,
            errors=tuple(errors),
        )

    def _expired_sources(self) -> list[DatabaseRow]:
        now = datetime.now()
        with connect(self._db_path) as connection:
            init_db(connection)
            rows = connection.execute(
                """
                SELECT id, report_id, status, source_storage, source_object_key,
                       source_file_path, completed_at, updated_at
                FROM report_processing_jobs
                WHERE status IN ('completed', 'failed')
                  AND source_storage <> 'deleted'
                  AND (source_object_key <> '' OR source_file_path <> '')
                ORDER BY id
                """
            ).fetchall()

        result: list[DatabaseRow] = []
        for row in rows:
            retention_days = self._retention_days(str(row["status"]))
            if retention_days <= 0:
                continue
            reference = parse_timestamp(row["completed_at"]) or parse_timestamp(row["updated_at"])
            if reference is not None and reference < now - timedelta(days=retention_days):
                result.append(row)
        return result

    def _retention_days(self, status: str) -> int:
        if status == "failed":
            return max(self._settings.failed_source_retention_days, 0)
        return max(self._settings.completed_source_retention_days, 0)

    def _mark_deleted(self, row: DatabaseRow) -> None:
        source_path = str(row["source_file_path"] or "")
        report_id = row["report_id"]
        with connect(self._db_path) as connection:
            init_db(connection)
            connection.execute(
                """
                UPDATE report_processing_jobs
                SET source_storage = 'deleted',
                    source_object_key = '',
                    source_file_path = '',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (row["id"],),
            )
            if report_id is not None and source_path:
                connection.execute(
                    """
                    UPDATE annual_reports
                    SET source_file_path = ''
                    WHERE id = ? AND source_file_path = ?
                    """,
                    (report_id, source_path),
                )
            connection.commit()


def default_storage_factory(settings: Settings, storage_kind: str) -> SourceStorage:
    return source_storage_from_settings(settings, storage_kind=storage_kind)


def parse_timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
