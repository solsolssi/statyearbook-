from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path

from app.db.connection import DB_PATH, DatabaseConnection, connect
from app.db.schema import init_db
from app.yearbook_data.excel_series import SeriesDataset, parse_series_workbook


IMPORT_KINDS = {"full", "incremental"}


@dataclass(frozen=True)
class SeriesImportResult:
    batch_id: int
    dataset_count: int
    row_count: int
    reused: bool = False


class SeriesImportRepository:
    """Store immutable Excel revisions before an annual-report snapshot is built."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def import_workbook(
        self,
        source_path: Path,
        *,
        import_kind: str,
        target_year: int | None = None,
        persisted_source_path: str | None = None,
    ) -> SeriesImportResult:
        if import_kind not in IMPORT_KINDS:
            raise ValueError(
                f"import_kind는 {', '.join(sorted(IMPORT_KINDS))} 중 하나여야 합니다."
            )
        path = source_path.expanduser().resolve()
        source_hash = file_digest(path)
        datasets = parse_series_workbook(path)
        imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                existing = connection.execute(
                    """
                    SELECT id, summary_json
                    FROM series_import_batches
                    WHERE file_hash = ? AND import_kind = ?
                      AND target_year IS NOT DISTINCT FROM ?
                    """,
                    (source_hash, import_kind, target_year),
                ).fetchone()
                if existing is not None:
                    summary = json.loads(str(existing["summary_json"] or "{}"))
                    return SeriesImportResult(
                        batch_id=int(existing["id"]),
                        dataset_count=int(summary.get("datasets") or 0),
                        row_count=int(summary.get("rows") or 0),
                        reused=True,
                    )

                cursor = connection.execute(
                    """
                    INSERT INTO series_import_batches (
                        source_file_name, source_file_path, file_hash,
                        import_kind, target_year, status, imported_at
                    ) VALUES (?, ?, ?, ?, ?, 'importing', ?)
                    """,
                    (
                        path.name,
                        persisted_source_path or str(path),
                        source_hash,
                        import_kind,
                        target_year,
                        imported_at,
                    ),
                )
                batch_id = int(cursor.lastrowid)
                row_count = 0
                for dataset in datasets:
                    dataset_id = self._upsert_dataset(connection, dataset)
                    version_id = self._ensure_version(
                        connection,
                        dataset_id=dataset_id,
                        batch_id=batch_id,
                        dataset=dataset,
                    )
                    self._insert_observations(
                        connection,
                        version_id=version_id,
                        batch_id=batch_id,
                        dataset=dataset,
                    )
                    row_count += len(dataset.rows)

                summary = {"datasets": len(datasets), "rows": row_count}
                connection.execute(
                    """
                    UPDATE series_import_batches
                    SET status = 'imported', summary_json = ?
                    WHERE id = ?
                    """,
                    (json.dumps(summary, ensure_ascii=False), batch_id),
                )
        return SeriesImportResult(
            batch_id=batch_id,
            dataset_count=len(datasets),
            row_count=row_count,
        )

    def latest_rows(self, source_key: str) -> list[dict[str, object]]:
        """Return the newest revision of each period/dimension observation."""

        with connect(self._db_path) as connection:
            init_db(connection)
            rows = connection.execute(
                """
                SELECT observation.*, version.columns_json,
                       version.dimension_columns_json, dataset.title
                FROM statistical_observations observation
                JOIN statistical_dataset_versions version
                  ON version.id = observation.dataset_version_id
                JOIN statistical_datasets dataset ON dataset.id = version.dataset_id
                WHERE dataset.source_key = ?
                  AND observation.id = (
                      SELECT candidate.id
                      FROM statistical_observations candidate
                      JOIN statistical_dataset_versions candidate_version
                        ON candidate_version.id = candidate.dataset_version_id
                      WHERE candidate_version.dataset_id = dataset.id
                        AND candidate.period = observation.period
                        AND candidate.dimension_key = observation.dimension_key
                      ORDER BY candidate.source_batch_id DESC, candidate.id DESC
                      LIMIT 1
                  )
                ORDER BY observation.period, observation.dimension_key
                """,
                (source_key,),
            ).fetchall()
            return [
                {
                    **{key: row[key] for key in row.keys()},
                    "dimension_values": json.loads(row["dimension_values_json"] or "[]"),
                    "values": json.loads(row["values_json"] or "[]"),
                    "columns": json.loads(row["columns_json"] or "[]"),
                }
                for row in rows
            ]

    def _upsert_dataset(
        self,
        connection: DatabaseConnection,
        dataset: SeriesDataset,
    ) -> int:
        connection.execute(
            """
            INSERT INTO statistical_datasets (source_key, title)
            VALUES (?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                title = excluded.title,
                status = 'active',
                updated_at = CURRENT_TIMESTAMP
            """,
            (dataset.source_key, dataset.title),
        )
        row = connection.execute(
            "SELECT id FROM statistical_datasets WHERE source_key = ?",
            (dataset.source_key,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"시계열 데이터셋을 저장하지 못했습니다: {dataset.title}")
        return int(row["id"])

    def _ensure_version(
        self,
        connection: DatabaseConnection,
        *,
        dataset_id: int,
        batch_id: int,
        dataset: SeriesDataset,
    ) -> int:
        row = connection.execute(
            """
            SELECT id
            FROM statistical_dataset_versions
            WHERE dataset_id = ? AND structure_signature = ?
            """,
            (dataset_id, dataset.structure_signature),
        ).fetchone()
        if row is not None:
            return int(row["id"])

        cursor = connection.execute(
            """
            INSERT INTO statistical_dataset_versions (
                dataset_id, structure_signature, header_row_count,
                period_column, dimension_columns_json, columns_json,
                source_batch_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dataset_id,
                dataset.structure_signature,
                dataset.header_row_count,
                dataset.period_column,
                json.dumps(dataset.dimension_columns, ensure_ascii=False),
                json.dumps(
                    [asdict(column) for column in dataset.columns],
                    ensure_ascii=False,
                ),
                batch_id,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_observations(
        self,
        connection: DatabaseConnection,
        *,
        version_id: int,
        batch_id: int,
        dataset: SeriesDataset,
    ) -> None:
        connection.executemany(
            """
            INSERT INTO statistical_observations (
                dataset_version_id, source_batch_id, period, dimension_key,
                dimension_values_json, values_json, source_sheet,
                source_row_number
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    version_id,
                    batch_id,
                    row.period,
                    row.dimension_key,
                    json.dumps(row.dimensions, ensure_ascii=False),
                    json.dumps(row.values, ensure_ascii=False),
                    dataset.source_sheet,
                    row.source_row_number,
                )
                for row in dataset.rows
            ],
        )


def file_digest(source_path: Path) -> str:
    digest = hashlib.sha256()
    with source_path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
