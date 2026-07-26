from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.core.config import Settings
from app.services.report_import_service import (
    LocalUploadStore,
    ReportImportRequest,
    ReportImportService,
    ReportUploadError,
    infer_report_year,
    validated_filename,
)
from app.workflows.report_processing import ReportProcessingWorkflow


async def chunks(*values: bytes):  # type: ignore[no-untyped-def]
    for value in values:
        yield value


class ReportImportServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_upload_is_streamed_and_job_is_created(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                upload_dir=root / "uploads",
                max_upload_bytes=1024,
                auto_import_include_llm=False,
            )
            workflow = ReportProcessingWorkflow(root / "report.sqlite")
            service = ReportImportService(settings=settings, workflow=workflow)

            job = await service.create_job(
                ReportImportRequest(filename="2027 연보.xlsx"),
                chunks(b"first", b"-second"),
            )

            self.assertEqual(job["report_year"], 2027)
            self.assertEqual(job["status"], "queued")
            source_path = Path(str(job["source_file_path"]))
            self.assertEqual(source_path.read_bytes(), b"first-second")

    async def test_oversized_upload_removes_partial_file(self) -> None:
        with TemporaryDirectory() as directory:
            upload_dir = Path(directory) / "uploads"
            store = LocalUploadStore(upload_dir, max_bytes=5)

            with self.assertRaisesRegex(ReportUploadError, "크기"):
                await store.save("report.xlsx", chunks(b"1234", b"56"))

            self.assertEqual(list(upload_dir.iterdir()), [])

    async def test_empty_upload_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            store = LocalUploadStore(Path(directory), max_bytes=5)

            with self.assertRaisesRegex(ReportUploadError, "비어"):
                await store.save("report.xlsx", chunks(b""))

    def test_filename_validation_and_year_inference(self) -> None:
        self.assertEqual(validated_filename("../../2028 연보.HWPX"), "2028 연보.HWPX")
        self.assertEqual(infer_report_year("2028 연보.HWPX"), 2028)
        self.assertEqual(infer_report_year("연보.xlsx", fallback_year=2030), 2030)
        with self.assertRaises(ReportUploadError):
            validated_filename("report.csv")


if __name__ == "__main__":
    unittest.main()
