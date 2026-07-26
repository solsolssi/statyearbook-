from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ContextManager, Protocol
from uuid import uuid4

from app.core.config import Settings


class SourceStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredSource:
    storage_kind: str
    object_key: str
    filename: str
    size: int
    sha256: str
    local_path: Path | None = None

    @property
    def persisted_path(self) -> str:
        if self.storage_kind == "local" and self.local_path is not None:
            return str(self.local_path)
        return f"{self.storage_kind}://{self.object_key}"


class SourceStorage(Protocol):
    async def save(
        self,
        filename: str,
        chunks: AsyncIterable[bytes],
        *,
        max_bytes: int,
    ) -> StoredSource: ...

    def materialize(self, object_key: str, filename: str) -> ContextManager[Path]: ...

    def delete(self, object_key: str) -> None: ...


class LocalSourceStorage:
    storage_kind = "local"

    def __init__(self, root: Path) -> None:
        self._root = root

    async def save(
        self,
        filename: str,
        chunks: AsyncIterable[bytes],
        *,
        max_bytes: int,
    ) -> StoredSource:
        self._root.mkdir(parents=True, exist_ok=True)
        destination = self._root / f"{uuid4().hex}_{filename}"
        size, sha256 = await stream_to_path(destination, chunks, max_bytes=max_bytes)
        return StoredSource(
            storage_kind=self.storage_kind,
            object_key=str(destination),
            filename=filename,
            size=size,
            sha256=sha256,
            local_path=destination,
        )

    @contextmanager
    def materialize(self, object_key: str, filename: str) -> Iterator[Path]:
        del filename
        path = Path(object_key)
        if not path.is_file():
            raise SourceStorageError(f"업로드 원본 파일을 찾을 수 없습니다: {path}")
        yield path

    def delete(self, object_key: str) -> None:
        Path(object_key).unlink(missing_ok=True)


class ObjectSourceStorage:
    """S3-compatible source storage for AWS S3, Cloudflare R2 and MinIO."""

    storage_kind = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        temp_dir: Path,
        endpoint: str = "",
        region: str = "auto",
        access_key: str = "",
        secret_key: str = "",
        client: Any | None = None,
    ) -> None:
        if not bucket:
            raise SourceStorageError("OBJECT_STORAGE_BUCKET이 설정되지 않았습니다.")
        self._bucket = bucket
        self._temp_dir = temp_dir
        self._client = client or create_s3_client(
            endpoint=endpoint,
            region=region,
            access_key=access_key,
            secret_key=secret_key,
        )

    async def save(
        self,
        filename: str,
        chunks: AsyncIterable[bytes],
        *,
        max_bytes: int,
    ) -> StoredSource:
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        temporary = self._temp_dir / f"{uuid4().hex}_{filename}"
        try:
            size, sha256 = await stream_to_path(temporary, chunks, max_bytes=max_bytes)
            object_key = f"annual-reports/{sha256}/{filename}"
            await asyncio.to_thread(
                self._client.upload_file,
                str(temporary),
                self._bucket,
                object_key,
            )
        finally:
            temporary.unlink(missing_ok=True)
        return StoredSource(
            storage_kind=self.storage_kind,
            object_key=object_key,
            filename=filename,
            size=size,
            sha256=sha256,
        )

    @contextmanager
    def materialize(self, object_key: str, filename: str) -> Iterator[Path]:
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=self._temp_dir) as directory:
            path = Path(directory) / filename
            self._client.download_file(self._bucket, object_key, str(path))
            yield path

    def delete(self, object_key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=object_key)


async def stream_to_path(
    destination: Path,
    chunks: AsyncIterable[bytes],
    *,
    max_bytes: int,
) -> tuple[int, str]:
    size = 0
    digest = hashlib.sha256()
    try:
        with destination.open("wb") as output:
            async for chunk in chunks:
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    raise SourceStorageError("업로드 가능한 파일 크기를 초과했습니다.")
                digest.update(chunk)
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if size == 0:
        destination.unlink(missing_ok=True)
        raise SourceStorageError("업로드 파일이 비어 있습니다.")
    return size, digest.hexdigest()


def source_storage_from_settings(
    settings: Settings,
    *,
    storage_kind: str | None = None,
) -> SourceStorage:
    selected = (storage_kind or settings.source_storage_backend).strip().lower()
    if selected == "local":
        return LocalSourceStorage(settings.upload_dir)
    if selected in {"s3", "r2", "object"}:
        return ObjectSourceStorage(
            bucket=settings.object_storage_bucket,
            temp_dir=settings.upload_dir / ".materialized",
            endpoint=settings.object_storage_endpoint,
            region=settings.object_storage_region,
            access_key=settings.object_storage_access_key,
            secret_key=settings.object_storage_secret_key,
        )
    raise SourceStorageError(f"지원하지 않는 원본 저장소입니다: {selected}")


def create_s3_client(
    *,
    endpoint: str,
    region: str,
    access_key: str,
    secret_key: str,
) -> Any:
    try:
        import boto3
    except ImportError as error:
        raise SourceStorageError(
            "객체 저장소를 사용하려면 boto3 패키지가 필요합니다."
        ) from error
    options: dict[str, str] = {"region_name": region}
    if endpoint:
        options["endpoint_url"] = endpoint
    if access_key:
        options["aws_access_key_id"] = access_key
    if secret_key:
        options["aws_secret_access_key"] = secret_key
    return boto3.client("s3", **options)
