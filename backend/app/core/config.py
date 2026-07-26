from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from app.core.env import env_flag, load_local_env_file
from app.core.env import env_value


class Settings(BaseModel):
    app_name: str = "Annual Statistics Review API"
    api_prefix: str = "/api"
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]
    allowed_origin_regex: str | None = None
    upload_dir: Path = Path(__file__).resolve().parents[2] / "uploads"
    max_upload_bytes: int = 100 * 1024 * 1024
    auto_import_include_llm: bool = False
    source_storage_backend: str = "local"
    object_storage_bucket: str = ""
    object_storage_endpoint: str = ""
    object_storage_region: str = "auto"
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""
    job_executor_backend: str = "inprocess"
    job_lease_seconds: int = 300
    completed_source_retention_days: int = 365
    failed_source_retention_days: int = 90


@lru_cache
def get_settings() -> Settings:
    load_local_env_file()
    return Settings(
        allowed_origins=env_list(
            "ALLOWED_ORIGINS",
            default=[
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:5174",
                "http://127.0.0.1:5174",
            ],
        ),
        allowed_origin_regex=env_value("ALLOWED_ORIGIN_REGEX") or None,
        upload_dir=Path(
            env_value(
                "UPLOAD_DIR",
                default=str(Path(__file__).resolve().parents[2] / "uploads"),
            )
        ),
        max_upload_bytes=int(env_value("MAX_UPLOAD_BYTES", default=str(100 * 1024 * 1024))),
        auto_import_include_llm=env_flag("AUTO_IMPORT_INCLUDE_LLM", default=False),
        source_storage_backend=env_value("SOURCE_STORAGE_BACKEND", default="local"),
        object_storage_bucket=env_value("OBJECT_STORAGE_BUCKET"),
        object_storage_endpoint=env_value("OBJECT_STORAGE_ENDPOINT"),
        object_storage_region=env_value("OBJECT_STORAGE_REGION", default="auto"),
        object_storage_access_key=env_value("OBJECT_STORAGE_ACCESS_KEY"),
        object_storage_secret_key=env_value("OBJECT_STORAGE_SECRET_KEY"),
        job_executor_backend=env_value("JOB_EXECUTOR_BACKEND", default="inprocess"),
        job_lease_seconds=int(env_value("JOB_LEASE_SECONDS", default="300")),
        completed_source_retention_days=int(
            env_value("COMPLETED_SOURCE_RETENTION_DAYS", default="365")
        ),
        failed_source_retention_days=int(
            env_value("FAILED_SOURCE_RETENTION_DAYS", default="90")
        ),
    )


def env_list(name: str, *, default: list[str]) -> list[str]:
    raw_value = env_value(name)
    if not raw_value:
        return default
    return [value.strip() for value in raw_value.split(",") if value.strip()]
