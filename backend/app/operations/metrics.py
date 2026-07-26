from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from app.db.connection import DB_PATH, DatabaseRow, connect
from app.db.schema import init_db
from app.models.operations import (
    JobOperationMetrics,
    LLMOperationMetrics,
    OperationsOverview,
    StageOperationMetrics,
)


class OperationsMetricsService:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def overview(
        self,
        *,
        window_days: int = 30,
        report_id: int | None = None,
    ) -> OperationsOverview:
        days = max(1, min(window_days, 365))
        cutoff = timestamp(datetime.now() - timedelta(days=days))
        with connect(self._db_path) as connection:
            init_db(connection)
            report_filter = " AND report_id = ?" if report_id is not None else ""
            params: tuple[object, ...] = (
                (cutoff, report_id) if report_id is not None else (cutoff,)
            )
            jobs = connection.execute(
                f"""
                SELECT status, started_at, completed_at
                FROM report_processing_jobs
                WHERE created_at >= ?{report_filter}
                """,
                params,
            ).fetchall()

            stage_report_filter = " AND j.report_id = ?" if report_id is not None else ""
            stages = connection.execute(
                f"""
                SELECT s.stage_name, s.status, s.started_at, s.completed_at
                FROM report_processing_stages s
                JOIN report_processing_jobs j ON j.id = s.job_id
                WHERE j.created_at >= ?{stage_report_filter}
                """,
                params,
            ).fetchall()

            llm_report_filter = " AND vr.report_id = ?" if report_id is not None else ""
            llm_usage = connection.execute(
                f"""
                SELECT u.provider, u.model, u.request_kind,
                       u.input_tokens, u.output_tokens, u.total_tokens,
                       u.estimated_cost_usd
                FROM llm_usage_events u
                JOIN validation_runs vr ON vr.id = u.run_id
                WHERE u.created_at >= ?{llm_report_filter}
                """,
                params,
            ).fetchall()

        llm_metrics = summarize_llm_usage(llm_usage)
        return OperationsOverview(
            generated_at=timestamp(),
            window_days=days,
            report_id=report_id,
            jobs=summarize_jobs(jobs),
            stages=summarize_stages(stages),
            llm_usage=llm_metrics,
            llm_total_tokens=sum(metric.total_tokens for metric in llm_metrics),
            llm_estimated_cost_usd=round(
                sum(metric.estimated_cost_usd for metric in llm_metrics),
                8,
            ),
        )


def summarize_jobs(rows: Iterable[DatabaseRow]) -> JobOperationMetrics:
    items = list(rows)
    counts = status_counts(items)
    terminal = counts["completed"] + counts["failed"]
    return JobOperationMetrics(
        total=len(items),
        queued=counts["queued"],
        running=counts["running"],
        completed=counts["completed"],
        failed=counts["failed"],
        failure_rate_percent=percentage(counts["failed"], terminal),
        average_duration_seconds=average_duration(items),
    )


def summarize_stages(rows: Iterable[DatabaseRow]) -> list[StageOperationMetrics]:
    grouped: dict[str, list[DatabaseRow]] = defaultdict(list)
    for row in rows:
        grouped[str(row["stage_name"])].append(row)

    result: list[StageOperationMetrics] = []
    for stage, items in grouped.items():
        counts = status_counts(items)
        terminal = counts["completed"] + counts["failed"]
        result.append(
            StageOperationMetrics(
                stage=stage,
                attempts=len(items),
                completed=counts["completed"],
                failed=counts["failed"],
                failure_rate_percent=percentage(counts["failed"], terminal),
                average_duration_seconds=average_duration(items),
            )
        )
    return sorted(result, key=lambda item: stage_order(item.stage))


def summarize_llm_usage(rows: Iterable[DatabaseRow]) -> list[LLMOperationMetrics]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row["provider"]),
            str(row["model"]),
            str(row["request_kind"]),
        )
        totals = grouped.setdefault(
            key,
            {
                "requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
            },
        )
        totals["requests"] += 1
        totals["input_tokens"] += int(row["input_tokens"] or 0)
        totals["output_tokens"] += int(row["output_tokens"] or 0)
        totals["total_tokens"] += int(row["total_tokens"] or 0)
        totals["estimated_cost_usd"] += float(row["estimated_cost_usd"] or 0)

    return [
        LLMOperationMetrics(
            provider=provider,
            model=model,
            request_kind=request_kind,
            requests=int(totals["requests"]),
            input_tokens=int(totals["input_tokens"]),
            output_tokens=int(totals["output_tokens"]),
            total_tokens=int(totals["total_tokens"]),
            estimated_cost_usd=round(float(totals["estimated_cost_usd"]), 8),
        )
        for (provider, model, request_kind), totals in sorted(grouped.items())
    ]


def status_counts(rows: Iterable[DatabaseRow]) -> defaultdict[str, int]:
    counts: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row["status"])] += 1
    return counts


def average_duration(rows: Iterable[DatabaseRow]) -> float:
    durations = [
        duration_seconds(row["started_at"], row["completed_at"])
        for row in rows
    ]
    completed = [duration for duration in durations if duration is not None]
    return round(sum(completed) / len(completed), 3) if completed else 0


def duration_seconds(started_at: object, completed_at: object) -> float | None:
    started = parse_timestamp(started_at)
    completed = parse_timestamp(completed_at)
    if started is None or completed is None or completed < started:
        return None
    return (completed - started).total_seconds()


def parse_timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def percentage(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0


def timestamp(value: datetime | None = None) -> str:
    return (value or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


def stage_order(stage: str) -> tuple[int, str]:
    known = {
        "import": 0,
        "calculation_validation": 1,
        "language_validation": 2,
    }
    return known.get(stage, 99), stage
