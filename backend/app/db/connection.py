from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
import sqlite3
from types import TracebackType
from typing import Any, Protocol, TypeVar

from app.core.env import env_value, load_local_env_file
from app.db.postgres import PostgresConnection


load_local_env_file()
DB_PATH = Path(
    env_value(
        "ANNUAL_STATISTICS_DB_PATH",
        default=str(Path(__file__).with_name("annual_statistics.sqlite")),
    )
).expanduser()
SUPPORTED_DATABASE_BACKENDS = {"auto", "sqlite", "postgres"}


class DatabaseRow(Protocol):
    def __getitem__(self, key: str | int) -> Any: ...

    def keys(self) -> Iterable[str]: ...


class DatabaseCursor(Protocol):
    lastrowid: int | None

    @property
    def rowcount(self) -> int: ...

    def fetchone(self) -> DatabaseRow | None: ...

    def fetchall(self) -> list[DatabaseRow]: ...

    def __iter__(self) -> Iterator[DatabaseRow]: ...


ConnectionT = TypeVar("ConnectionT", bound="DatabaseConnection")


class DatabaseConnection(Protocol):
    def execute(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
    ) -> DatabaseCursor: ...

    def executemany(
        self,
        sql: str,
        params_seq: Iterable[Sequence[Any]],
    ) -> DatabaseCursor: ...

    def executescript(self, script: str) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...

    def __enter__(self: ConnectionT) -> ConnectionT: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


def configured_database_backend(db_path: Path | None = None) -> str:
    """Resolve the database backend without making a network connection.

    Explicit temporary paths always use SQLite so tests and one-off imports do
    not accidentally write to the production database. The default ``auto``
    mode preserves deployment compatibility by using PostgreSQL when
    ``DATABASE_URL`` exists and SQLite otherwise.
    """

    load_local_env_file()
    resolved_path = Path(db_path) if db_path is not None else DB_PATH
    if resolved_path != DB_PATH:
        return "sqlite"

    backend = env_value("DATABASE_BACKEND", default="auto").lower()
    if backend not in SUPPORTED_DATABASE_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_DATABASE_BACKENDS))
        raise RuntimeError(
            f"DATABASE_BACKEND 값이 올바르지 않습니다: {backend!r}. "
            f"사용 가능 값: {supported}"
        )
    if backend == "auto":
        return "postgres" if env_value("DATABASE_URL") else "sqlite"
    return backend


def connect(db_path: Path | None = None) -> DatabaseConnection:
    backend = configured_database_backend(db_path)
    if backend == "postgres":
        database_url = env_value("DATABASE_URL")
        if not database_url:
            raise RuntimeError(
                "DATABASE_BACKEND=postgres 이지만 DATABASE_URL이 설정되지 않았습니다."
            )
        return PostgresConnection(database_url)

    resolved_path = Path(db_path) if db_path is not None else DB_PATH
    return connect_sqlite(resolved_path)


def connect_sqlite(db_path: Path = DB_PATH) -> DatabaseConnection:
    """Open SQLite explicitly at adapter boundaries such as data migration tools."""

    resolved_path = Path(db_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resolved_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
