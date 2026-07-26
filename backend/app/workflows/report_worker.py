from __future__ import annotations

import argparse
import socket
import time
from uuid import uuid4

from app.core.config import get_settings
from app.workflows.report_job_repository import ReportProcessingJobRepository
from app.workflows.report_processing import ReportProcessingError, ReportProcessingWorkflow


class ReportProcessingWorker:
    def __init__(
        self,
        *,
        workflow: ReportProcessingWorkflow | None = None,
        jobs: ReportProcessingJobRepository | None = None,
        worker_id: str | None = None,
    ) -> None:
        self._jobs = jobs or ReportProcessingJobRepository()
        self._workflow = workflow or ReportProcessingWorkflow(job_repository=self._jobs)
        self._worker_id = worker_id or f"{socket.gethostname()}-{uuid4().hex[:8]}"

    def run_once(self) -> bool:
        job_id = self._jobs.next_claimable_job_id()
        if job_id is None:
            return False
        try:
            self._workflow.run(job_id, lease_owner=self._worker_id)
        except ReportProcessingError:
            pass
        return True

    def run_forever(self, *, poll_seconds: float = 2.0) -> None:
        while True:
            if not self.run_once():
                time.sleep(max(poll_seconds, 0.1))


def main() -> None:
    parser = argparse.ArgumentParser(description="Process queued annual-report imports.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    worker = ReportProcessingWorker()
    if args.once:
        worker.run_once()
    else:
        worker.run_forever(poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    main()
