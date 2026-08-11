from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path

from app.db.connection import DB_PATH, DatabaseConnection, connect
from app.db.schema import init_db


_SOURCE_VALUES_RELATION: ContextVar[str] = ContextVar(
    "source_values_relation",
    default="statistical_values",
)
_SOURCE_ITEMS_RELATION: ContextVar[str] = ContextVar(
    "source_items_relation",
    default="statistical_dataset_items",
)


@dataclass(frozen=True)
class SourceDataSnapshot:
    id: int
    report_id: int | None
    parent_snapshot_id: int | None
    source_batch_id: int
    target_year: int


class SourceSnapshotService:
    """Own immutable source-ledger lineages for individual annual reports.

    The normalized source tables remain the shared import store.  A snapshot
    records exactly which import batches a report may see, so later uploads do
    not change an already generated report's source view.
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def ensure_for_report(
        self,
        connection: DatabaseConnection,
        *,
        report_id: int,
    ) -> SourceDataSnapshot:
        existing = snapshot_for_report(connection, report_id)
        if existing is not None:
            return existing

        report = connection.execute(
            "SELECT id, year FROM annual_reports WHERE id = ?",
            (report_id,),
        ).fetchone()
        if report is None:
            raise ValueError("원장 스냅샷을 연결할 기준 연보를 찾을 수 없습니다.")
        full_batch = connection.execute(
            """
            SELECT id
            FROM series_import_batches
            WHERE import_kind = 'relational_full' AND status = 'imported'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if full_batch is None:
            raise ValueError("기준이 될 전체 통계 원장이 아직 적재되지 않았습니다.")
        batch_id = int(full_batch["id"])
        cursor = connection.execute(
            """
            INSERT INTO source_data_snapshots (
                report_id, parent_snapshot_id, source_batch_id,
                target_year, snapshot_kind
            ) VALUES (?, NULL, ?, ?, 'full_base')
            """,
            (report_id, batch_id, int(report["year"]) - 1),
        )
        snapshot_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO source_snapshot_batches (
                snapshot_id, source_batch_id, precedence, visible_through_year
            ) VALUES (?, ?, 0, ?)
            """,
            (snapshot_id, batch_id, int(report["year"]) - 1),
        )
        return SourceDataSnapshot(
            id=snapshot_id,
            report_id=report_id,
            parent_snapshot_id=None,
            source_batch_id=batch_id,
            target_year=int(report["year"]) - 1,
        )

    def create_child(
        self,
        connection: DatabaseConnection,
        *,
        base_report_id: int,
        source_batch_id: int,
        target_year: int,
    ) -> SourceDataSnapshot:
        if connection.execute(
            "SELECT 1 FROM series_import_batches WHERE id = ? AND status = 'imported'",
            (source_batch_id,),
        ).fetchone() is None:
            raise ValueError("반영할 증분 원장 적재 기록을 찾을 수 없습니다.")
        parent = self.ensure_for_report(connection, report_id=base_report_id)
        cursor = connection.execute(
            """
            INSERT INTO source_data_snapshots (
                report_id, parent_snapshot_id, source_batch_id,
                target_year, snapshot_kind
            ) VALUES (NULL, ?, ?, ?, 'incremental')
            """,
            (parent.id, source_batch_id, target_year),
        )
        snapshot_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO source_snapshot_batches (
                snapshot_id, source_batch_id, precedence, visible_through_year
            )
            SELECT ?, source_batch_id, precedence, visible_through_year
            FROM source_snapshot_batches
            WHERE snapshot_id = ?
            ORDER BY precedence
            """,
            (snapshot_id, parent.id),
        )
        included = connection.execute(
            """
            SELECT 1 FROM source_snapshot_batches
            WHERE snapshot_id = ? AND source_batch_id = ?
            """,
            (snapshot_id, source_batch_id),
        ).fetchone()
        if included is None:
            next_precedence = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(precedence), -1) + 1 AS value
                    FROM source_snapshot_batches
                    WHERE snapshot_id = ?
                    """,
                    (snapshot_id,),
                ).fetchone()["value"]
            )
            connection.execute(
                """
                INSERT INTO source_snapshot_batches (
                    snapshot_id, source_batch_id, precedence, visible_through_year
                ) VALUES (?, ?, ?, ?)
                """,
                (snapshot_id, source_batch_id, next_precedence, target_year),
            )
        return SourceDataSnapshot(
            id=snapshot_id,
            report_id=None,
            parent_snapshot_id=parent.id,
            source_batch_id=source_batch_id,
            target_year=target_year,
        )

    def attach_report(
        self,
        connection: DatabaseConnection,
        *,
        snapshot_id: int,
        report_id: int,
    ) -> None:
        connection.execute(
            """
            UPDATE source_data_snapshots
            SET report_id = ?
            WHERE id = ? AND report_id IS NULL
            """,
            (report_id, snapshot_id),
        )

    def discard_orphan(self, snapshot_id: int) -> None:
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                connection.execute(
                    """
                    DELETE FROM source_data_snapshots
                    WHERE id = ? AND report_id IS NULL
                    """,
                    (snapshot_id,),
                )


def snapshot_for_report(
    connection: DatabaseConnection,
    report_id: int,
) -> SourceDataSnapshot | None:
    row = connection.execute(
        """
        SELECT id, report_id, parent_snapshot_id, source_batch_id, target_year
        FROM source_data_snapshots
        WHERE report_id = ?
        """,
        (report_id,),
    ).fetchone()
    if row is None:
        return None
    return SourceDataSnapshot(
        id=int(row["id"]),
        report_id=int(row["report_id"]),
        parent_snapshot_id=(
            int(row["parent_snapshot_id"])
            if row["parent_snapshot_id"] is not None
            else None
        ),
        source_batch_id=int(row["source_batch_id"]),
        target_year=int(row["target_year"]),
    )


def source_values_relation() -> str:
    return _SOURCE_VALUES_RELATION.get()


def source_items_relation() -> str:
    return _SOURCE_ITEMS_RELATION.get()


@contextmanager
def activate_source_snapshot(
    connection: DatabaseConnection,
    snapshot_id: int | None,
) -> Iterator[None]:
    if snapshot_id is None:
        yield
        return
    snapshot_row = connection.execute(
        "SELECT target_year FROM source_data_snapshots WHERE id = ? AND status = 'active'",
        (snapshot_id,),
    ).fetchone()
    if snapshot_row is None:
        raise ValueError("사용할 원장 스냅샷을 찾을 수 없습니다.")
    snapshot_target_year = int(snapshot_row["target_year"])

    connection.execute("DROP VIEW IF EXISTS snapshot_statistical_values")
    connection.execute("DROP VIEW IF EXISTS snapshot_statistical_dataset_items")
    connection.execute(
        f"""
        CREATE TEMP VIEW snapshot_statistical_values AS
        WITH versions AS (
            SELECT
                value.id AS statistical_value_id,
                value.dataset_id,
                value.data_cycle,
                value.period,
                value.data_division,
                value.item_data_no,
                value.class_data_no,
                value.data_value,
                value.string_value,
                value.comment_identifier,
                value.comment_text,
                value.english_comment_text,
                value.write_state,
                value.check_code,
                value.verified,
                value.verification_result,
                value.source_sequence,
                value.source_registered_at,
                value.source_batch_id,
                value.updated_at
            FROM statistical_values value
            UNION ALL
            SELECT
                value.id AS statistical_value_id,
                value.dataset_id,
                value.data_cycle,
                value.period,
                value.data_division,
                value.item_data_no,
                value.class_data_no,
                revision.data_value,
                revision.string_value,
                revision.comment_identifier,
                revision.comment_text,
                revision.english_comment_text,
                revision.write_state,
                revision.check_code,
                revision.verified,
                revision.verification_result,
                value.source_sequence,
                value.source_registered_at,
                revision.source_batch_id,
                revision.archived_at AS updated_at
            FROM statistical_value_revisions revision
            JOIN statistical_values value
              ON value.id = revision.statistical_value_id
        ), ranked AS (
            SELECT
                versions.*,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        versions.dataset_id,
                        versions.data_cycle,
                        versions.period,
                        versions.data_division,
                        versions.item_data_no,
                        versions.class_data_no
                    ORDER BY batches.precedence DESC
                ) AS version_rank
            FROM versions
            JOIN source_snapshot_batches batches
              ON batches.source_batch_id = versions.source_batch_id
             AND batches.snapshot_id = {int(snapshot_id)}
            WHERE SUBSTR(versions.period, 1, 4) NOT BETWEEN '1900' AND '2200'
               OR CAST(SUBSTR(versions.period, 1, 4) AS INTEGER)
                    <= COALESCE(batches.visible_through_year, {snapshot_target_year})
        )
        SELECT
            statistical_value_id AS id,
            dataset_id, data_cycle, period, data_division,
            item_data_no, class_data_no, data_value, string_value,
            comment_identifier, comment_text, english_comment_text,
            write_state, check_code, verified, verification_result,
            source_sequence, source_registered_at, source_batch_id, updated_at
        FROM ranked
        WHERE version_rank = 1
        """
    )
    connection.execute(
        f"""
        CREATE TEMP VIEW snapshot_statistical_dataset_items AS
        WITH versions AS (
            SELECT
                item.id AS statistical_dataset_item_id,
                item.dataset_id,
                item.item_id,
                item.level,
                item.item_data_no,
                item.item_name,
                item.data_type,
                item.is_dummy,
                item.input_required,
                item.max_level,
                item.is_leaf,
                item.full_name,
                item.display_order,
                item.is_deleted,
                item.source_batch_id,
                item.updated_at
            FROM statistical_dataset_items item
            UNION ALL
            SELECT
                item.id AS statistical_dataset_item_id,
                item.dataset_id,
                revision.item_id,
                revision.level,
                item.item_data_no,
                revision.item_name,
                revision.data_type,
                revision.is_dummy,
                revision.input_required,
                revision.max_level,
                revision.is_leaf,
                revision.full_name,
                revision.display_order,
                revision.is_deleted,
                revision.source_batch_id,
                revision.archived_at AS updated_at
            FROM statistical_dataset_item_revisions revision
            JOIN statistical_dataset_items item
              ON item.id = revision.statistical_dataset_item_id
        ), eligible AS (
            SELECT
                versions.*,
                ROW_NUMBER() OVER (
                    PARTITION BY versions.dataset_id, versions.item_data_no
                    ORDER BY batches.precedence DESC
                ) AS version_rank
            FROM versions
            JOIN source_snapshot_batches batches
              ON batches.source_batch_id = versions.source_batch_id
             AND batches.snapshot_id = {int(snapshot_id)}
        )
        SELECT
            statistical_dataset_item_id AS id,
            dataset_id, item_id, level, item_data_no, item_name,
            data_type, is_dummy, input_required, max_level, is_leaf,
            full_name, display_order, source_batch_id, updated_at
        FROM eligible
        WHERE version_rank = 1 AND is_deleted = 0
        """
    )
    values_token: Token[str] = _SOURCE_VALUES_RELATION.set(
        "snapshot_statistical_values"
    )
    items_token: Token[str] = _SOURCE_ITEMS_RELATION.set(
        "snapshot_statistical_dataset_items"
    )
    try:
        yield
    finally:
        _SOURCE_VALUES_RELATION.reset(values_token)
        _SOURCE_ITEMS_RELATION.reset(items_token)
        connection.execute("DROP VIEW IF EXISTS snapshot_statistical_values")
        connection.execute("DROP VIEW IF EXISTS snapshot_statistical_dataset_items")
