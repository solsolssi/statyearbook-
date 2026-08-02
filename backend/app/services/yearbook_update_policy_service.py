from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from app.db.connection import DB_PATH, DatabaseConnection, connect
from app.db.schema import init_db
from app.models.yearbook_reproduction import ReproductionTableAnalysis
from app.services.yearbook_reproduction_service import YearbookReproductionService


NUMBER_PATTERN = re.compile(r"[-+]?\d[\d,\s]*(?:\.\d+)?%?")


@dataclass(frozen=True)
class TableUpdatePolicy:
    table_code: str
    update_mode: str
    window_size: int
    no_update_action: str
    structure_change_action: str
    text_update_action: str


@dataclass(frozen=True)
class EditionManifestEntry:
    edition_year: int
    table_code: str
    lifecycle_status: str
    target_period: str
    source_dataset_id: int | None
    title: str
    table_order: int
    unit: str
    notes: str
    is_inferred: bool


class YearbookUpdatePolicyService:
    """Persist how each table changes and what happened in one edition."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def synchronize(self, *, report_id: int) -> None:
        overview = YearbookReproductionService(self._db_path).overview(report_id=report_id)
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                for table in overview.tables:
                    update_mode = infer_update_mode(connection, table)
                    existing_policy = connection.execute(
                        """
                        SELECT table_code, no_update_action
                        FROM yearbook_table_update_policies
                        WHERE table_code = ?
                        """,
                        (table.code,),
                    ).fetchone()
                    if existing_policy is None:
                        connection.execute(
                            """
                            INSERT INTO yearbook_table_update_policies (
                                table_code, update_mode, window_size,
                                no_update_action, structure_change_action,
                                text_update_action, source_report_id,
                                source_table_id, notes
                            ) VALUES (?, ?, ?, 'require_manifest',
                                      'source_native_preview',
                                      'source_then_template', ?, ?, ?)
                            """,
                            (
                                table.code,
                                update_mode,
                                max(1, table.period_rule.count),
                                overview.report_id,
                                table.table_id,
                                automatic_policy_note(update_mode),
                            ),
                        )

                    lifecycle_status = infer_lifecycle_status(table)
                    if (
                        lifecycle_status == "missing"
                        and existing_policy is not None
                        and str(existing_policy["no_update_action"]) == "carry_forward"
                    ):
                        lifecycle_status = "no_change"
                    existing_manifest = connection.execute(
                        """
                        SELECT id, is_inferred
                        FROM yearbook_edition_manifest
                        WHERE edition_year = ? AND table_code = ?
                        """,
                        (overview.report_year, table.code),
                    ).fetchone()
                    values = (
                        lifecycle_status,
                        table.period_rule.target_period,
                        table.source_dataset_id,
                        table.title,
                        table.table_order,
                        table.reason,
                    )
                    if existing_manifest is None:
                        connection.execute(
                            """
                            INSERT INTO yearbook_edition_manifest (
                                edition_year, table_code, lifecycle_status,
                                target_period, source_dataset_id, title,
                                table_order, notes, is_inferred
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                            """,
                            (overview.report_year, table.code, *values),
                        )
                    elif bool(existing_manifest["is_inferred"]):
                        connection.execute(
                            """
                            UPDATE yearbook_edition_manifest
                            SET lifecycle_status = ?, target_period = ?,
                                source_dataset_id = ?, title = ?,
                                table_order = ?, notes = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (*values, int(existing_manifest["id"])),
                        )

    def policies(
        self,
        connection: DatabaseConnection,
    ) -> dict[str, TableUpdatePolicy]:
        rows = connection.execute(
            """
            SELECT table_code, update_mode, window_size, no_update_action,
                   structure_change_action, text_update_action
            FROM yearbook_table_update_policies
            """
        ).fetchall()
        return {
            str(row["table_code"]): TableUpdatePolicy(
                table_code=str(row["table_code"]),
                update_mode=str(row["update_mode"]),
                window_size=int(row["window_size"] or 1),
                no_update_action=str(row["no_update_action"]),
                structure_change_action=str(row["structure_change_action"]),
                text_update_action=str(row["text_update_action"]),
            )
            for row in rows
        }

    def manifest(
        self,
        connection: DatabaseConnection,
        *,
        edition_year: int,
    ) -> dict[str, EditionManifestEntry]:
        rows = connection.execute(
            """
            SELECT edition_year, table_code, lifecycle_status, target_period,
                   source_dataset_id, title, table_order, unit, notes,
                   is_inferred
            FROM yearbook_edition_manifest
            WHERE edition_year = ?
            ORDER BY table_order, table_code
            """,
            (edition_year,),
        ).fetchall()
        return {
            str(row["table_code"]): EditionManifestEntry(
                edition_year=int(row["edition_year"]),
                table_code=str(row["table_code"]),
                lifecycle_status=str(row["lifecycle_status"]),
                target_period=str(row["target_period"] or ""),
                source_dataset_id=(
                    int(row["source_dataset_id"])
                    if row["source_dataset_id"] is not None
                    else None
                ),
                title=str(row["title"] or ""),
                table_order=int(row["table_order"] or 0),
                unit=str(row["unit"] or ""),
                notes=str(row["notes"] or ""),
                is_inferred=bool(row["is_inferred"]),
            )
            for row in rows
        }


def infer_update_mode(
    connection: DatabaseConnection,
    table: ReproductionTableAnalysis,
) -> str:
    if table.materializer in {"period_rows", "period_columns"}:
        return "rolling_window"
    if data_is_text_only(connection, table.table_id):
        return "text_snapshot"
    return "full_snapshot"


def data_is_text_only(connection: DatabaseConnection, table_id: int) -> bool:
    values = connection.execute(
        """
        SELECT text_value
        FROM stat_table_cells
        WHERE table_id = ? AND COALESCE(is_header, 0) = 0
        """,
        (table_id,),
    ).fetchall()
    nonempty = [str(row["text_value"] or "").strip() for row in values]
    nonempty = [value for value in nonempty if value]
    return bool(nonempty) and not any(NUMBER_PATTERN.fullmatch(value.replace(",", "")) for value in nonempty)


def infer_lifecycle_status(table: ReproductionTableAnalysis) -> str:
    if table.mapping_status != "mapped":
        return "mapping_review"
    if table.generation_status != "basic_recipe":
        return "missing"
    return "updated"


def automatic_policy_note(update_mode: str) -> str:
    labels = {
        "rolling_window": "표시된 연도 창을 기준으로 자동 추론",
        "full_snapshot": "해당 기준기간의 전체 원장값으로 교체",
        "text_snapshot": "문자열 중심 표를 해당 기준기간 원장값으로 교체",
    }
    return labels.get(update_mode, "기존 연보 구조에서 자동 추론")
