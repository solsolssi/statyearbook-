from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from app.db.connection import DB_PATH, DatabaseConnection, DatabaseRow, connect
from app.db.schema import init_db
from app.models.report_updates import (
    ReportCellDifference,
    ReportComparisonSummary,
    ReportTableDifference,
    ReportUpdateSummary,
)
from app.validation.result_repository import refresh_run_issue_count


TABLE_METADATA_FIELDS = (
    "title",
    "title_en",
    "section_title",
    "section_title_en",
    "domain",
    "unit",
    "base_date",
    "note",
    "source",
)


class ReportUpdateService:
    """Persist exact report-to-report differences and reuse unchanged validation."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def record_update(
        self,
        *,
        base_report_id: int,
        report_id: int,
        update_kind: str = "completed_report_update",
    ) -> ReportUpdateSummary:
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                base_tables = tables_by_code(connection, base_report_id)
                current_tables = tables_by_code(connection, report_id)
                cursor = connection.execute(
                    """
                    INSERT INTO report_update_batches (
                        base_report_id, report_id, update_kind
                    ) VALUES (?, ?, ?)
                    """,
                    (base_report_id, report_id, update_kind),
                )
                batch_id = int(cursor.lastrowid)
                counts: defaultdict[str, int] = defaultdict(int)
                changed_table_ids: list[int] = []
                for code in sorted(set(base_tables) | set(current_tables), key=table_code_key):
                    base = base_tables.get(code)
                    current = current_tables.get(code)
                    change_type, metadata_changed, cell_diffs = compare_table_rows(
                        connection,
                        base,
                        current,
                    )
                    counts[change_type] += 1
                    counts["changed_cells"] += len(cell_diffs)
                    if change_type in {"modified", "added"} and current is not None:
                        changed_table_ids.append(int(current["id"]))
                    table_cursor = connection.execute(
                        """
                        INSERT INTO report_update_table_diffs (
                            batch_id, table_code, base_table_id, report_table_id,
                            change_type, metadata_changed, changed_cell_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            batch_id,
                            code,
                            int(base["id"]) if base is not None else None,
                            int(current["id"]) if current is not None else None,
                            change_type,
                            int(metadata_changed),
                            len(cell_diffs),
                        ),
                    )
                    table_diff_id = int(table_cursor.lastrowid)
                    if cell_diffs:
                        connection.executemany(
                            """
                            INSERT INTO report_update_cell_diffs (
                                table_diff_id, row_index, col_index,
                                previous_value, current_value
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            [
                                (table_diff_id, row, col, previous, current_value)
                                for row, col, previous, current_value in cell_diffs
                            ],
                        )
                connection.execute(
                    """
                    UPDATE report_update_batches
                    SET changed_table_count = ?, unchanged_table_count = ?,
                        added_table_count = ?, deleted_table_count = ?,
                        changed_cell_count = ?
                    WHERE id = ?
                    """,
                    (
                        counts["modified"],
                        counts["matching"],
                        counts["added"],
                        counts["deleted"],
                        counts["changed_cells"],
                        batch_id,
                    ),
                )
        return ReportUpdateSummary(
            batch_id=batch_id,
            base_report_id=base_report_id,
            report_id=report_id,
            update_kind=update_kind,
            changed_table_count=counts["modified"],
            unchanged_table_count=counts["matching"],
            added_table_count=counts["added"],
            deleted_table_count=counts["deleted"],
            changed_cell_count=counts["changed_cells"],
            changed_table_ids=changed_table_ids,
        )

    def reuse_unchanged_validation(self, *, batch_id: int, new_run_id: int) -> int:
        """Copy unchanged table results from the base report's latest run."""

        with connect(self._db_path) as connection:
            init_db(connection)
            batch = connection.execute(
                "SELECT base_report_id FROM report_update_batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
            if batch is None:
                return 0
            base_run = latest_run_id(connection, int(batch["base_report_id"]))
            if base_run is None:
                return 0
            mappings = connection.execute(
                """
                SELECT base_table_id, report_table_id
                FROM report_update_table_diffs
                WHERE batch_id = ? AND change_type = 'matching'
                  AND base_table_id IS NOT NULL AND report_table_id IS NOT NULL
                """,
                (batch_id,),
            ).fetchall()
            copied = 0
            with connection:
                for mapping in mappings:
                    old_table_id = int(mapping["base_table_id"])
                    new_table_id = int(mapping["report_table_id"])
                    cursor = connection.execute(
                        """
                        INSERT INTO validation_checks (
                            run_id, table_id, profile_id, rule_id, check_type,
                            check_label, location, row_index, col_index,
                            current_value, expected_value, difference, status,
                            severity, detail, formula, confidence
                        )
                        SELECT ?, ?, profile_id, rule_id, check_type,
                               check_label, location, row_index, col_index,
                               current_value, expected_value, difference, status,
                               severity, detail, formula, confidence
                        FROM validation_checks
                        WHERE run_id = ? AND table_id = ?
                        """,
                        (new_run_id, new_table_id, base_run, old_table_id),
                    )
                    copied += max(int(cursor.rowcount or 0), 0)
                    connection.execute(
                        """
                        INSERT INTO linguistic_review_candidates (
                            run_id, table_id, review_type, candidate_kind, source_kind,
                            location, row_index, col_index, current_value, korean_text,
                            english_text, glossary_json, reason, status, prompt_version,
                            reviewed_model, review_result_json, review_fingerprint,
                            resolution_source, created_at, reviewed_at
                        )
                        SELECT ?, ?, review_type, candidate_kind, source_kind,
                               location, row_index, col_index, current_value, korean_text,
                               english_text, glossary_json, reason, status, prompt_version,
                               reviewed_model, review_result_json, review_fingerprint,
                               'unchanged_table_reuse', created_at, reviewed_at
                        FROM linguistic_review_candidates
                        WHERE run_id = ? AND table_id = ?
                        """,
                        (new_run_id, new_table_id, base_run, old_table_id),
                    )
                connection.execute(
                    """
                    UPDATE validation_runs
                    SET scope_kind = 'changed_tables', base_run_id = ?
                    WHERE id = ?
                    """,
                    (base_run, new_run_id),
                )
                refresh_run_issue_count(connection, run_id=new_run_id)
            return copied


class ReportComparisonService:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def compare(self, *, left_report_id: int, right_report_id: int) -> ReportComparisonSummary:
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                left = tables_by_code(connection, left_report_id)
                right = tables_by_code(connection, right_report_id)
                cursor = connection.execute(
                    """
                    INSERT INTO report_comparison_runs (left_report_id, right_report_id)
                    VALUES (?, ?)
                    """,
                    (left_report_id, right_report_id),
                )
                run_id = int(cursor.lastrowid)
                counts: defaultdict[str, int] = defaultdict(int)
                results: list[ReportTableDifference] = []
                for code in sorted(set(left) | set(right), key=table_code_key):
                    left_table = left.get(code)
                    right_table = right.get(code)
                    change_type, _, cell_diffs = compare_table_rows(
                        connection,
                        left_table,
                        right_table,
                    )
                    counts[change_type] += 1
                    counts["changed_cells"] += len(cell_diffs)
                    result_cursor = connection.execute(
                        """
                        INSERT INTO report_comparison_table_results (
                            run_id, table_code, left_table_id, right_table_id,
                            change_type, changed_cell_count
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            code,
                            int(left_table["id"]) if left_table is not None else None,
                            int(right_table["id"]) if right_table is not None else None,
                            change_type,
                            len(cell_diffs),
                        ),
                    )
                    result_id = int(result_cursor.lastrowid)
                    if cell_diffs:
                        connection.executemany(
                            """
                            INSERT INTO report_comparison_cell_results (
                                table_result_id, row_index, col_index, left_value, right_value
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            [
                                (result_id, row, col, left_value, right_value)
                                for row, col, left_value, right_value in cell_diffs
                            ],
                        )
                    results.append(
                        ReportTableDifference(
                            table_code=code,
                            change_type=change_type,
                            changed_cell_count=len(cell_diffs),
                            cell_differences=[
                                ReportCellDifference(
                                    row_index=row,
                                    col_index=col,
                                    left_value=left_value,
                                    right_value=right_value,
                                )
                                for row, col, left_value, right_value in cell_diffs[:20]
                            ],
                        )
                    )
                connection.execute(
                    """
                    UPDATE report_comparison_runs
                    SET total_table_count = ?, matching_table_count = ?,
                        changed_table_count = ?, added_table_count = ?,
                        deleted_table_count = ?, changed_cell_count = ?
                    WHERE id = ?
                    """,
                    (
                        len(results),
                        counts["matching"],
                        counts["modified"],
                        counts["added"],
                        counts["deleted"],
                        counts["changed_cells"],
                        run_id,
                    ),
                )
        return ReportComparisonSummary(
            id=run_id,
            left_report_id=left_report_id,
            right_report_id=right_report_id,
            total_table_count=len(results),
            matching_table_count=counts["matching"],
            changed_table_count=counts["modified"],
            added_table_count=counts["added"],
            deleted_table_count=counts["deleted"],
            changed_cell_count=counts["changed_cells"],
            tables=results,
        )


def tables_by_code(
    connection: DatabaseConnection,
    report_id: int,
) -> dict[str, DatabaseRow]:
    rows = connection.execute(
        "SELECT * FROM stat_tables WHERE report_id = ? ORDER BY table_order, id",
        (report_id,),
    ).fetchall()
    return {str(row["code"]): row for row in rows}


def compare_table_rows(
    connection: DatabaseConnection,
    left: DatabaseRow | None,
    right: DatabaseRow | None,
) -> tuple[str, bool, list[tuple[int, int, str, str]]]:
    if left is None:
        return "added", True, all_cells_as_diffs(connection, right, left_missing=True)
    if right is None:
        return "deleted", True, all_cells_as_diffs(connection, left, left_missing=False)
    metadata_changed = any(str(left[field] or "") != str(right[field] or "") for field in TABLE_METADATA_FIELDS)
    left_cells = cells_by_coordinate(connection, int(left["id"]))
    right_cells = cells_by_coordinate(connection, int(right["id"]))
    cell_diffs = [
        (row, col, left_cells.get((row, col), ""), right_cells.get((row, col), ""))
        for row, col in sorted(set(left_cells) | set(right_cells))
        if left_cells.get((row, col), "") != right_cells.get((row, col), "")
    ]
    return (
        "modified" if metadata_changed or cell_diffs else "matching",
        metadata_changed,
        cell_diffs,
    )


def cells_by_coordinate(
    connection: DatabaseConnection,
    table_id: int,
) -> dict[tuple[int, int], str]:
    return {
        (int(row["row_index"]), int(row["col_index"])): str(row["text_value"] or "")
        for row in connection.execute(
            """
            SELECT row_index, col_index, text_value
            FROM stat_table_cells
            WHERE table_id = ?
            """,
            (table_id,),
        ).fetchall()
    }


def all_cells_as_diffs(
    connection: DatabaseConnection,
    table: DatabaseRow | None,
    *,
    left_missing: bool,
) -> list[tuple[int, int, str, str]]:
    if table is None:
        return []
    cells = cells_by_coordinate(connection, int(table["id"]))
    return [
        (row, col, "" if left_missing else value, value if left_missing else "")
        for (row, col), value in sorted(cells.items())
        if value
    ]


def latest_run_id(connection: DatabaseConnection, report_id: int) -> int | None:
    row = connection.execute(
        """
        SELECT id FROM validation_runs
        WHERE report_id = ?
        ORDER BY completed_at DESC, id DESC
        LIMIT 1
        """,
        (report_id,),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def table_code_key(code: str) -> tuple:
    parts: list[object] = []
    for item in code.replace("부록", "999-").replace(" 표", "-").split("-"):
        parts.append(int(item) if item.strip().isdigit() else item)
    return tuple(parts)
