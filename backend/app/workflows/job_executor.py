from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


JobRunner = Callable[[int, bool], None]
TaskScheduler = Callable[..., object]


class JobExecutor(Protocol):
    def submit(self, job_id: int, *, retry: bool = False) -> None: ...


class InProcessJobExecutor:
    """Schedule short local jobs through FastAPI's background-task adapter."""

    def __init__(self, scheduler: TaskScheduler, runner: JobRunner) -> None:
        self._scheduler = scheduler
        self._runner = runner

    def submit(self, job_id: int, *, retry: bool = False) -> None:
        self._scheduler(self._runner, job_id, retry)


class QueuedJobExecutor:
    """Leave the persisted job queued for an external Railway worker."""

    def submit(self, job_id: int, *, retry: bool = False) -> None:
        del job_id, retry
