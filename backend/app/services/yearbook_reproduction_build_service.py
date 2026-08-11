from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path

from app.db.connection import DB_PATH, DatabaseConnection, connect
from app.db.schema import init_db
from app.models.yearbook_reproduction import ReproductionBuildSummary
from app.services.confirmed_source_mapping_service import (
    ConfirmedSourceMappingService,
)
from app.services.yearbook_reproduction_service import (
    SUPPORTED_AUTOMATIC_MATERIALIZERS,
    YearbookReproductionService,
)
from app.services.yearbook_update_policy_service import YearbookUpdatePolicyService
from app.yearbook_data.relational_materializer import RelationalTableMaterializer
from app.yearbook_data.source_snapshots import activate_source_snapshot, snapshot_for_report


class YearbookReproductionBuildService:
    """Create a comparison-only staging build without publishing or validating it."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def run(
        self,
        *,
        report_id: int,
        report_year: int | None = None,
        target_data_year: int | None = None,
        source_snapshot_id: int | None = None,
    ) -> ReproductionBuildSummary:
        effective_source_snapshot_id = source_snapshot_id
        if effective_source_snapshot_id is None:
            with connect(self._db_path) as connection:
                init_db(connection)
                snapshot = snapshot_for_report(connection, report_id)
                if snapshot is not None:
                    effective_source_snapshot_id = snapshot.id
        confirmed_mapping_service = ConfirmedSourceMappingService(self._db_path)
        confirmed_mapping_service.synchronize()
        overview = YearbookReproductionService(self._db_path).overview(
            report_id=report_id,
            source_snapshot_id=effective_source_snapshot_id,
        )
        effective_report_year = report_year or overview.report_year
        effective_target_year = target_data_year or int(overview.target_data_period)
        if (
            effective_report_year != overview.report_year
            or effective_target_year != int(overview.target_data_period)
        ):
            overview = YearbookReproductionService(self._db_path).overview(
                report_id=report_id,
                source_snapshot_id=effective_source_snapshot_id,
                target_data_year=effective_target_year,
                recipe_year=effective_report_year,
            )
        policy_service = YearbookUpdatePolicyService(self._db_path)
        policy_service.synchronize(
            report_id=report_id,
            source_snapshot_id=effective_source_snapshot_id,
            edition_year=effective_report_year,
            target_data_year=effective_target_year,
        )
        confirmed_mapping_service.synchronize_manifest_decisions()
        materializer = RelationalTableMaterializer(self._db_path)
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection, activate_source_snapshot(
                connection,
                effective_source_snapshot_id,
            ):
                policies = policy_service.policies(connection)
                manifest = policy_service.manifest(
                    connection,
                    edition_year=effective_report_year,
                )
                cursor = connection.execute(
                    """
                    INSERT INTO yearbook_reproduction_runs (
                        baseline_report_id, report_year, target_data_year,
                        source_snapshot_id, status, created_at
                    ) VALUES (?, ?, ?, ?, 'running', ?)
                    """,
                    (
                        overview.report_id,
                        effective_report_year,
                        effective_target_year,
                        effective_source_snapshot_id,
                        created_at,
                    ),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("재현 비교 실행을 생성하지 못했습니다.")
                run_id = int(cursor.lastrowid)
                counts: Counter[str] = Counter()
                compared_cells = 0
                mismatch_cells = 0
                for table in overview.tables:
                    policy = policies.get(table.code)
                    manifest_entry = manifest.get(table.code)
                    lifecycle_status = (
                        manifest_entry.lifecycle_status
                        if manifest_entry is not None
                        else "updated"
                    )
                    source_dataset_id = (
                        manifest_entry.source_dataset_id
                        if manifest_entry is not None
                        and manifest_entry.source_dataset_id is not None
                        else table.source_dataset_id
                    )
                    source_lifecycle_status = latest_source_lifecycle_status(
                        connection,
                        snapshot_id=effective_source_snapshot_id,
                        dataset_id=source_dataset_id,
                    )
                    if (
                        lifecycle_status == "no_change"
                        and has_target_period_incremental_values(
                            connection,
                            snapshot_id=effective_source_snapshot_id,
                            dataset_id=source_dataset_id,
                            target_year=effective_target_year,
                        )
                    ):
                        # A former "no change" decision only applies while
                        # the increment has no value for this table's target
                        # period.  The presence of an actual incremental
                        # value must always reactivate source materialization.
                        lifecycle_status = "updated"
                    if (
                        source_lifecycle_status == "deleted"
                        and (manifest_entry is None or manifest_entry.is_inferred)
                    ):
                        lifecycle_status = "deleted"
                    recipe = connection.execute(
                        """
                        SELECT id
                        FROM yearbook_table_recipes
                        WHERE table_code = ?
                        ORDER BY revision DESC, id DESC
                        LIMIT 1
                        """,
                        (table.code,),
                    ).fetchone()
                    recipe_id = int(recipe["id"]) if recipe is not None else None
                    if lifecycle_status == "deleted":
                        status = "deleted"
                        result = None
                        error = manifest_entry.notes if manifest_entry is not None else "삭제된 통계입니다."
                    elif lifecycle_status == "empty":
                        result = materializer.materialize_with_connection(
                            connection,
                            table_id=table.table_id,
                            dataset_id=0,
                            materializer="empty_values",
                            target_year=effective_target_year,
                        )
                        status = "empty"
                        error = (
                            manifest_entry.notes
                            if manifest_entry is not None
                            else "사용자 결정에 따라 데이터 값을 비워 둡니다."
                        )
                    elif lifecycle_status in {"no_change", "static"}:
                        result = materializer.materialize_with_connection(
                            connection,
                            table_id=table.table_id,
                            dataset_id=source_dataset_id or 0,
                            materializer="copy",
                            target_year=effective_target_year,
                        )
                        status = (
                            "carried_forward"
                            if lifecycle_status == "no_change"
                            else "static"
                        )
                        error = (
                            "이번 연도 변경 없음이 명시되어 이전 연보 값을 승계했습니다."
                            if lifecycle_status == "no_change"
                            else "고정 통계로 지정되어 이전 연보 값을 유지했습니다."
                        )
                    elif lifecycle_status == "missing":
                        status = "source_missing"
                        result = None
                        error = table.reason or "해당 기준기간 원장값이 없습니다."
                    elif lifecycle_status == "new":
                        status = "recipe_required"
                        result = None
                        error = "신규 통계의 표 제목·순서·레이아웃 설정이 필요합니다."
                    elif table.mapping_status != "mapped":
                        status = "mapping_review"
                        result = None
                        error = table.reason
                    elif table.generation_status != "basic_recipe":
                        status = (
                            "source_missing"
                            if table.materializer in SUPPORTED_AUTOMATIC_MATERIALIZERS
                            else "recipe_required"
                        )
                        result = None
                        error = (
                            table.reason
                            if status == "source_missing"
                            else "표 분할·병합 등 개별 생성 규칙이 필요합니다."
                        )
                    elif source_dataset_id is None and table.materializer != "copy":
                        status = "mapping_review"
                        result = None
                        error = "연결된 원장 통계가 없습니다."
                    else:
                        result = materializer.materialize_with_connection(
                            connection,
                            table_id=table.table_id,
                            dataset_id=source_dataset_id or 0,
                            materializer=table.materializer,
                            target_year=effective_target_year,
                            allow_shape_change=bool(
                                policy
                                and policy.update_mode
                                in {"full_snapshot", "text_snapshot"}
                                and policy.structure_change_action
                                == "source_native_preview"
                            ),
                            update_mode=policy.update_mode if policy else "",
                        )
                        status = result.status
                        error = result.error
                    counts[status] += 1
                    cell_count = len(result.cells) if result is not None else 0
                    table_mismatches = result.mismatch_count if result is not None else 0
                    compared_cells += cell_count
                    if status == "source_difference":
                        mismatch_cells += table_mismatches
                    table_cursor = connection.execute(
                        """
                        INSERT INTO yearbook_reproduction_table_results (
                            run_id, baseline_table_id, recipe_id, source_dataset_id,
                            status, compared_cell_count, mismatch_count, error_message
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            table.table_id,
                            recipe_id,
                            source_dataset_id,
                            status,
                            cell_count,
                            table_mismatches,
                            error,
                        ),
                    )
                    if table_cursor.lastrowid is None:
                        raise RuntimeError(f"{table.code} 비교 결과를 저장하지 못했습니다.")
                    table_result_id = int(table_cursor.lastrowid)
                    if result is not None and result.cells:
                        connection.executemany(
                            """
                            INSERT INTO yearbook_reproduction_cell_results (
                                table_result_id, row_index, col_index,
                                expected_value, generated_value, is_match
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            [
                                (
                                    table_result_id,
                                    cell.row_index,
                                    cell.col_index,
                                    cell.expected_value,
                                    cell.generated_value,
                                    int(cell.matches),
                                )
                                for cell in result.cells
                            ],
                        )

                completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                summary = {
                    "total_tables": len(overview.tables),
                    "exact_tables": counts["exact"],
                    "mismatch_tables": counts["source_difference"],
                    "source_difference_tables": counts["source_difference"],
                    "carried_forward_tables": counts["carried_forward"],
                    "static_tables": counts["static"],
                    "empty_tables": counts["empty"],
                    "deleted_tables": counts["deleted"],
                    "source_missing_tables": counts["source_missing"],
                    "unavailable_tables": counts["unavailable"],
                    "recipe_required_tables": counts["recipe_required"],
                    "mapping_review_tables": counts["mapping_review"],
                    "compared_cells": compared_cells,
                    "mismatch_cells": mismatch_cells,
                    "source_difference_cells": mismatch_cells,
                }
                connection.execute(
                    """
                    UPDATE yearbook_reproduction_runs
                    SET status = 'completed', summary_json = ?, completed_at = ?
                    WHERE id = ?
                    """,
                    (json.dumps(summary, ensure_ascii=False), completed_at, run_id),
                )
        return ReproductionBuildSummary(
            id=run_id,
            report_id=overview.report_id,
            report_year=effective_report_year,
            target_data_year=effective_target_year,
            status="completed",
            created_at=created_at,
            completed_at=completed_at,
            **summary,
        )


def latest_source_lifecycle_status(
    connection: DatabaseConnection,
    *,
    snapshot_id: int | None,
    dataset_id: int | None,
) -> str:
    if snapshot_id is None or dataset_id is None:
        return ""
    row = connection.execute(
        """
        SELECT event.lifecycle_status
        FROM statistical_dataset_lifecycle_events event
        JOIN source_snapshot_batches batch
          ON batch.source_batch_id = event.source_batch_id
         AND batch.snapshot_id = ?
        WHERE event.dataset_id = ?
        ORDER BY batch.precedence DESC, event.id DESC
        LIMIT 1
        """,
        (snapshot_id, dataset_id),
    ).fetchone()
    return str(row["lifecycle_status"] or "") if row is not None else ""


def has_target_period_incremental_values(
    connection: DatabaseConnection,
    *,
    snapshot_id: int | None,
    dataset_id: int | None,
    target_year: int,
) -> bool:
    if snapshot_id is None or dataset_id is None:
        return False
    row = connection.execute(
        """
        SELECT 1
        FROM statistical_values value
        JOIN source_snapshot_batches membership
          ON membership.source_batch_id = value.source_batch_id
         AND membership.snapshot_id = ?
        JOIN series_import_batches batch
          ON batch.id = membership.source_batch_id
         AND batch.import_kind = 'relational_incremental'
        WHERE value.dataset_id = ?
          AND CAST(SUBSTR(value.period, 1, 4) AS INTEGER) = ?
          AND ? <= COALESCE(membership.visible_through_year, ?)
        LIMIT 1
        """,
        (snapshot_id, dataset_id, target_year, target_year, target_year),
    ).fetchone()
    return row is not None
