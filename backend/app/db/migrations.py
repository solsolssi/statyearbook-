from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Lock

from app.db import schema
from app.db.connection import DatabaseConnection, connect


_INITIALIZED_DATABASES: set[str] = set()
_INITIALIZATION_LOCK = Lock()


DATA_MIGRATIONS = (
    ("retire_metadata_validation_v2", schema.retire_metadata_validation),
    ("restore_metadata_presence_validation_v1", schema.restore_metadata_validation),
    (
        "repair_misaligned_linguistic_reviews_v1",
        schema.repair_misaligned_linguistic_reviews,
    ),
    ("restore_semantic_type_qualifiers_v1", schema.restore_semantic_type_qualifiers),
    ("retire_terminology_validation_v1", schema.retire_terminology_validation),
    ("canonical_validation_results_v1", schema.canonicalize_validation_results),
)


def ensure_database_ready(
    connection: DatabaseConnection,
    *,
    force: bool = False,
) -> None:
    """Create schema and apply each data migration once per database process."""

    key = database_connection_key(connection)
    if not force and key in _INITIALIZED_DATABASES:
        return

    with _INITIALIZATION_LOCK:
        if not force and key in _INITIALIZED_DATABASES:
            return
        schema.create_schema(connection)
        schema.ensure_schema_columns(connection)
        for migration_key, migration in DATA_MIGRATIONS:
            apply_data_migration(connection, migration_key, migration)
        schema.seed_validation_rule_definitions(connection)
        connection.commit()
        _INITIALIZED_DATABASES.add(key)


def initialize_default_database() -> None:
    with connect() as connection:
        ensure_database_ready(connection)


def apply_data_migration(
    connection: DatabaseConnection,
    key: str,
    migration: Callable[[DatabaseConnection], None],
) -> None:
    if connection.execute(
        "SELECT 1 FROM schema_migrations WHERE key = ?",
        (key,),
    ).fetchone():
        return
    migration(connection)
    connection.execute("INSERT INTO schema_migrations (key) VALUES (?)", (key,))


def database_connection_key(connection: DatabaseConnection) -> str:
    database_url = getattr(connection, "database_url", None)
    if database_url:
        return f"postgres:{database_url}"

    try:
        row = connection.execute("PRAGMA database_list").fetchone()
    except Exception:
        return f"connection:{id(connection)}"
    if row is None:
        return f"connection:{id(connection)}"

    try:
        file_name = str(row["file"] or "")
    except (KeyError, TypeError, IndexError):
        file_name = str(row[2] or "")
    if not file_name:
        return f"sqlite-memory:{id(connection)}"

    path = Path(file_name).resolve()
    try:
        inode = path.stat().st_ino
    except OSError:
        inode = 0
    return f"sqlite:{path}:{inode}"


def reset_initialization_cache() -> None:
    """Test helper for databases recreated at the same path."""

    _INITIALIZED_DATABASES.clear()
