from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote

from app.core.contact_metadata import parse_contact_metadata
from app.db.connection import DB_PATH, DatabaseConnection, DatabaseRow, connect
from app.db.schema import init_db
from app.domain.enums import TableStatus
from app.models.report import (
    ChangeItem,
    ColumnDefinition,
    Metric,
    PressInsight,
    ReportOverviewPayload,
    ReportPayload,
    ReportDeleteResult,
    ReportSummary,
    StatTable,
    StatTablePart,
    StatTableSummary,
    TableDownloadCatalogItem,
    TableMetadata,
    TableHierarchyItem,
    ValidationIssue,
    Visualization,
    VisualizationSeries,
)
from app.ingest.table_repairs import (
    detach_spanning_small_business_note,
    normalize_flood_insurance_small_business_guide,
    repair_local_government_sejong_eup_myeon_dong_column,
)
from app.ingest.table_shape import wide_row_oriented_text_table_header_count
from app.validation.models import restore_hyphenated_line_breaks
from app.validation.presentation import display_check_type, validation_issue_from_row
from app.validation.spec_repository import load_rule_specs_by_id


GENERATION_STATUS_LABELS = {
    "exact": "생성값 일치",
    "source_difference": "업로드값 반영",
    "carried_forward": "이전 값 승계",
    "static": "고정 통계",
    "empty": "빈 값 유지",
    "unavailable": "생성 확인 필요",
    "source_missing": "증분 데이터 없음",
    "mapping_review": "증분 연결",
    "parse_review": "파싱 확인",
    "recipe_required": "생성 규칙 필요",
    "increment_applied": "증분 반영",
    "increment_no_change": "증분 변경 없음",
    "new_table": "신규 통계 확인",
}


def generation_status_label(status: str) -> str:
    return GENERATION_STATUS_LABELS.get(status, status)


class DatabaseReportService:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def get_payload_for_report(self, report_id: int | None = None) -> ReportPayload:
        report = self._resolve_report(report_id)
        tables = self.list_tables(
            report_id,
            include_highlights=False,
            include_passing_checks=False,
        )
        return ReportPayload(
            summary=self._summary_from_tables(report, tables),
            tables=tables,
            press_insights=self._press_insights_from_tables(tables),
            available_reports=self.list_reports(),
            available_templates=self.list_templates(),
        )

    def get_overview_for_report(self, report_id: int | None = None) -> ReportOverviewPayload:
        """Return list data without serializing every source cell.

        The existing report endpoint remains available for compatibility. New
        clients use this projection and request one table detail on demand.
        """

        report = self._resolve_report(report_id)
        tables = self.list_tables(
            report_id,
            include_highlights=False,
            include_passing_checks=False,
        )
        validated_types_by_code = (
            self._validated_types_by_table_code(int(report["id"])) if report is not None else {}
        )
        return ReportOverviewPayload(
            summary=self._summary_from_tables(report, tables),
            tables=[
                table_summary(
                    table,
                    validated_types=validated_types_by_code.get(table.code, []),
                )
                for table in tables
            ],
            press_insights=self._press_insights_from_tables(tables),
            available_reports=self.list_reports(),
            available_templates=self.list_templates(),
        )

    def _summary_from_tables(
        self,
        report: DatabaseRow | None,
        tables: list[StatTable],
    ) -> ReportSummary:
        if report is None:
            return ReportSummary(
                report_id=None,
                file_name="",
                base_year="",
                total_tables=0,
                normal_count=0,
                needs_review_count=0,
                suspected_error_count=0,
                issue_counts={},
                validation_scope="none",
            )

        issue_counts: dict[str, int] = {}
        for table in tables:
            for check in table.checks:
                if check.status == "정상":
                    continue
                issue_counts[check.type] = issue_counts.get(check.type, 0) + 1
        with connect(self._db_path) as connection:
            update = connection.execute(
                """
                SELECT changed_table_count, unchanged_table_count
                FROM report_update_batches
                WHERE report_id = ?
                ORDER BY id DESC LIMIT 1
                """,
                (int(report["id"]),),
            ).fetchone()
            run = connection.execute(
                """
                SELECT scope_kind, selected_rules_json,
                       reused_report_count, reused_table_count, reused_check_count
                FROM validation_runs
                WHERE report_id = ?
                ORDER BY completed_at DESC, id DESC LIMIT 1
                """,
                (int(report["id"]),),
            ).fetchone()

        return ReportSummary(
            report_id=int(report["id"]),
            file_name=decode_display_text(report["source_file_name"]),
            base_year=str(report["year"]),
            total_tables=len(tables),
            normal_count=sum(1 for table in tables if table.status == "normal"),
            needs_review_count=sum(1 for table in tables if table.status == "needs_review"),
            suspected_error_count=sum(1 for table in tables if table.status == "suspected_error"),
            issue_counts=issue_counts,
            origin_kind=str(report["origin_kind"] or ""),
            base_report_id=(
                int(report["base_report_id"])
                if report["base_report_id"] is not None
                else None
            ),
            validation_scope=(
                str(run["scope_kind"])
                if run is not None
                else "none"
            ),
            changed_table_count=int(update["changed_table_count"] or 0) if update else 0,
            unchanged_table_count=int(update["unchanged_table_count"] or 0) if update else 0,
            selected_validation_keys=(
                json_list(str(run["selected_rules_json"] or "[]"))
                if run is not None
                else []
            ),
            reused_report_count=int(run["reused_report_count"] or 0) if run else 0,
            reused_table_count=int(run["reused_table_count"] or 0) if run else 0,
            reused_check_count=int(run["reused_check_count"] or 0) if run else 0,
        )

    def list_tables(
        self,
        report_id: int | None = None,
        *,
        include_highlights: bool = True,
        include_passing_checks: bool = True,
    ) -> list[StatTable]:
        report = self._resolve_report(report_id)
        if report is None:
            return []

        with connect(self._db_path) as connection:
            init_db(connection)
            rows = connection.execute(
                """
                SELECT *
                FROM stat_tables
                WHERE report_id = ?
                ORDER BY table_order, id
                """,
                (report["id"],),
            ).fetchall()
            run_id = self._latest_run_id(connection, report["id"])
            cells_by_table = load_cells_by_table(connection, [int(row["id"]) for row in rows])
            checks_by_table: dict[int, list[DatabaseRow]] = {}
            specs_by_rule_id: dict[str, dict[str, Any]] = {}
            if run_id is not None:
                check_rows = load_checks_for_tables(
                    connection,
                    run_id,
                    [int(row["id"]) for row in rows],
                    include_passing=include_passing_checks,
                )
                checks_by_table = group_rows_by_int(check_rows, "table_id")
                specs_by_rule_id = load_rule_specs_by_id(connection, check_rows)

            physical_tables = [
                self._row_to_table(
                    connection,
                    report,
                    row,
                    run_id,
                    cells=cells_by_table.get(int(row["id"]), []),
                    check_rows=checks_by_table.get(int(row["id"]), []),
                    specs_by_rule_id=specs_by_rule_id,
                    include_highlights=include_highlights,
                )
                for row in rows
            ]
            return group_table_parts(physical_tables)

    def list_download_catalog(self, report_id: int) -> list[TableDownloadCatalogItem]:
        """List logical table ids without materializing cells or validation results."""
        report = self._resolve_report(report_id)
        if report is None:
            return []

        with connect(self._db_path) as connection:
            init_db(connection)
            rows = connection.execute(
                """
                SELECT id, code, title
                FROM stat_tables
                WHERE report_id = ?
                ORDER BY table_order, id
                """,
                (report["id"],),
            ).fetchall()

        grouped: dict[str, list[DatabaseRow]] = {}
        order: list[str] = []
        for row in rows:
            code = base_table_code(str(row["code"]))
            if code not in grouped:
                grouped[code] = []
                order.append(code)
            grouped[code].append(row)

        return [
            TableDownloadCatalogItem(
                id=(
                    f"group-{code}"
                    if len(grouped[code]) > 1
                    else f"db-{grouped[code][0]['id']}"
                ),
                code=code,
                title=strip_part_suffix(str(grouped[code][0]["title"])),
            )
            for code in order
        ]

    def get_table(self, table_id: str, report_id: int | None = None) -> StatTable | None:
        report = self._resolve_report(report_id)
        if report is None:
            return None

        with connect(self._db_path) as connection:
            init_db(connection)
            table_rows = self._table_rows_for_detail(connection, report, table_id)
            if not table_rows:
                return None

            run_id = self._latest_run_id(connection, report["id"])
            table_ids = [int(row["id"]) for row in table_rows]
            cells_by_table = load_cells_by_table(connection, table_ids)
            check_rows = load_checks_for_tables(connection, run_id, table_ids) if run_id is not None else []
            checks_by_table = group_rows_by_int(check_rows, "table_id")
            specs_by_rule_id = load_rule_specs_by_id(connection, check_rows)

            physical_tables = [
                self._row_to_table(
                    connection,
                    report,
                    row,
                    run_id,
                    cells=cells_by_table.get(int(row["id"]), []),
                    check_rows=checks_by_table.get(int(row["id"]), []),
                    specs_by_rule_id=specs_by_rule_id,
                    include_highlights=True,
                )
                for row in table_rows
            ]
            grouped = group_table_parts(physical_tables)
            return grouped[0] if grouped else None

    def _table_rows_for_detail(
        self,
        connection: DatabaseConnection,
        report: DatabaseRow,
        table_id: str,
    ) -> list[DatabaseRow]:
        if table_id.startswith("db-"):
            raw_id = table_id.removeprefix("db-")
            if not raw_id.isdigit():
                return []
            return connection.execute(
                """
                SELECT *
                FROM stat_tables
                WHERE report_id = ? AND id = ?
                ORDER BY table_order, id
                """,
                (report["id"], int(raw_id)),
            ).fetchall()

        base_code = table_id.removeprefix("group-")
        return connection.execute(
            """
            SELECT *
            FROM stat_tables
            WHERE report_id = ?
              AND (code = ? OR code LIKE ?)
            ORDER BY table_order, id
            """,
            (report["id"], base_code, f"{base_code} 표%"),
        ).fetchall()

    def _press_insights_from_tables(self, tables: list[StatTable]) -> list[PressInsight]:
        insights: list[PressInsight] = []

        for table in tables:
            if len(insights) >= 3:
                break
            metric = table.key_figures[0] if table.key_figures else None
            if not metric:
                continue
            insights.append(
                PressInsight(
                    id=f"press-{table.id}",
                    table_id=table.id,
                    title=f"{table.title} 주요 수치",
                    body=f"{table.title}에서 {metric.label}은 {metric.value}입니다.",
                    tone="notable",
                )
            )

        return insights

    def list_reports(self) -> list:
        with connect(self._db_path) as connection:
            init_db(connection)
            rows = connection.execute(
                """
                SELECT r.id, r.year, r.title, r.source_file_name, r.imported_at, r.origin_kind
                FROM annual_reports r
                WHERE COALESCE(r.is_archived, 0) = 0
                  AND COALESCE(r.origin_kind, 'uploaded') != 'ledger_generated'
                GROUP BY r.id
                ORDER BY r.year DESC, r.imported_at DESC, r.id DESC
                """
            ).fetchall()
            reports = [
                {
                    "id": int(row["id"]),
                    "year": int(row["year"]),
                    "title": (
                        f"{row['title']} · 초안"
                        if str(row["origin_kind"] or "") in {"incremental_draft", "upload_draft"}
                        else row["title"]
                    ),
                    "file_name": decode_display_text(row["source_file_name"]),
                    "imported_at": row["imported_at"],
                    "table_count": self._logical_table_count(connection, int(row["id"])),
                    "kind": "published",
                }
                for row in rows
            ]
            # The former virtual "test report" was a read-only view over a
            # global-ledger build.  Increment uploads now create real drafts,
            # so legacy build artefacts must not appear in the report selector.
            return reports

    def delete_report(self, report_id: int) -> ReportDeleteResult | None:
        if report_id <= 0:
            raise ValueError("삭제할 연보를 찾을 수 없습니다.")

        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                report = connection.execute(
                    """
                    SELECT id, title, is_archived, is_template
                    FROM annual_reports
                    WHERE id = ?
                    """,
                    (report_id,),
                ).fetchone()
                if report is None:
                    return None

                if int(report["is_template"] or 0):
                    raise ValueError("숨김 템플릿 연보는 삭제할 수 없습니다.")
                if int(report["is_archived"] or 0):
                    raise ValueError("보관된 기준 연보는 삭제할 수 없습니다.")

                table_count = int(
                    connection.execute(
                        "SELECT COUNT(*) AS count FROM stat_tables WHERE report_id = ?",
                        (report_id,),
                    ).fetchone()["count"]
                )
                validation_run_count = int(
                    connection.execute(
                        "SELECT COUNT(*) AS count FROM validation_runs WHERE report_id = ?",
                        (report_id,),
                    ).fetchone()["count"]
                )

                # Processing jobs are operational records for the same upload.  Delete
                # them before annual_reports turns the foreign keys into NULL, so a
                # removed test snapshot does not leave a stale retry target in the UI.
                connection.execute(
                    "DELETE FROM report_processing_jobs WHERE report_id = ?",
                    (report_id,),
                )
                connection.execute("DELETE FROM annual_reports WHERE id = ?", (report_id,))

                return ReportDeleteResult(
                    report_id=report_id,
                    title=str(report["title"]),
                    table_count=table_count,
                    validation_run_count=validation_run_count,
                )

    def list_templates(self) -> list:
        with connect(self._db_path) as connection:
            init_db(connection)
            rows = connection.execute(
                """
                SELECT id, year, title, source_file_name, imported_at
                FROM annual_reports
                WHERE COALESCE(is_archived, 0) = 1
                  AND COALESCE(is_template, 0) = 1
                ORDER BY year DESC, imported_at DESC, id DESC
                """
            ).fetchall()
            return [
                {
                    "id": int(row["id"]),
                    "year": int(row["year"]),
                    "title": str(row["title"]),
                    "file_name": decode_display_text(row["source_file_name"]),
                    "imported_at": str(row["imported_at"] or ""),
                    "table_count": self._logical_table_count(connection, int(row["id"])),
                    "kind": "template",
                }
                for row in rows
            ]

    def _latest_report(self) -> DatabaseRow | None:
        with connect(self._db_path) as connection:
            init_db(connection)
            return connection.execute(
                """
                SELECT *
                FROM annual_reports
                WHERE COALESCE(is_archived, 0) = 0
                  AND COALESCE(origin_kind, 'uploaded') != 'ledger_generated'
                ORDER BY imported_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()

    def _report_by_id(self, report_id: int) -> DatabaseRow | None:
        with connect(self._db_path) as connection:
            init_db(connection)
            return connection.execute(
                "SELECT * FROM annual_reports WHERE id = ?",
                (report_id,),
            ).fetchone()

    def _resolve_report(self, report_id: int | None = None) -> DatabaseRow | None:
        if report_id is not None:
            report = self._report_by_id(report_id)
            if report is not None:
                return report
        return self._latest_report()

    def _logical_table_count(self, connection: DatabaseConnection, report_id: int) -> int:
        rows = connection.execute(
            "SELECT code FROM stat_tables WHERE report_id = ?",
            (report_id,),
        ).fetchall()
        return len({re.sub(r"\s+표\d+$", "", row["code"]) for row in rows})

    def _validated_types_by_table_code(self, report_id: int) -> dict[str, list[str]]:
        """Return compact validation coverage for the list view.

        The overview deliberately omits passing check rows to keep the initial
        page responsive.  A list filter still needs to know that a normal
        table was checked for (for example) a ratio, so expose only its
        distinct display types rather than every passing check result.
        """

        with connect(self._db_path) as connection:
            init_db(connection)
            run_id = self._latest_run_id(connection, report_id)
            if run_id is None:
                return {}
            rows = connection.execute(
                """
                SELECT source_table.code, checks.check_type
                FROM validation_checks AS checks
                JOIN stat_tables AS source_table ON source_table.id = checks.table_id
                JOIN validation_runs AS source_run ON source_run.id = checks.run_id
                WHERE checks.run_id = ?
                  AND source_table.report_id = ?
                  AND (
                    source_table.edited_after_run_id IS NULL
                    OR source_run.id > source_table.edited_after_run_id
                  )
                GROUP BY source_table.code, checks.check_type
                ORDER BY source_table.code, checks.check_type
                """,
                (run_id, report_id),
            ).fetchall()

        covered: dict[str, set[str]] = {}
        for row in rows:
            code = base_table_code(str(row["code"]))
            covered.setdefault(code, set()).add(display_check_type(str(row["check_type"])))
        return {code: sorted(types) for code, types in covered.items()}

    def _row_to_table(
        self,
        connection: DatabaseConnection,
        report: DatabaseRow,
        table_row: DatabaseRow,
        run_id: int | None,
        *,
        cells: list[DatabaseRow] | None = None,
        check_rows: list[DatabaseRow] | None = None,
        specs_by_rule_id: dict[str, dict[str, Any]] | None = None,
        include_highlights: bool = True,
    ) -> StatTable:
        if cells is None:
            cells = connection.execute(
                """
                SELECT row_index, col_index, text_value, numeric_value, is_header, footnote_marker
                FROM stat_table_cells
                WHERE table_id = ?
                ORDER BY row_index, col_index
                """,
                (table_row["id"],),
            ).fetchall()

        matrix = matrix_from_cells(cells)
        footnote_matrix = footnote_matrix_from_cells(cells)
        display_notes = apply_display_matrix_repairs(
            str(table_row["code"]),
            matrix,
            footnote_matrix,
        )
        header_count = header_count_from_cells(cells, matrix)
        label_column_indexes = leading_label_column_indexes(matrix, header_count)
        columns = build_columns(
            matrix,
            header_count,
            label_column_indexes,
            table_code=table_row["code"],
            footnote_matrix=footnote_matrix,
        )
        rows = build_rows(matrix, columns, header_count, footnote_matrix, label_column_indexes)
        table_id = f"db-{table_row['id']}"
        validation_stale = table_validation_is_stale(connection, run_id, table_row)
        checks = build_validation_issues(
            connection,
            run_id,
            table_row["id"],
            header_count,
            matrix,
            check_rows=check_rows,
            specs_by_rule_id=specs_by_rule_id,
            include_highlights=include_highlights,
        )
        status, status_label = status_from_checks(checks)
        if (
            run_id is None
            and str(report["origin_kind"] or "") in {
                "incremental_draft",
                "upload_draft",
                "incremental_confirmed",
                "uploaded",
            }
            and status == TableStatus.NORMAL
        ):
            status_label = "검수 전"
        if validation_stale:
            status = TableStatus.NEEDS_REVIEW
            status_label = "재검수 필요"
        contact = parse_contact_metadata(table_row["source"] or "")
        generation = connection.execute(
            """
            SELECT generation_status, generation_message
            FROM generated_report_table_status
            WHERE report_id = ? AND table_id = ?
            """,
            (int(report["id"]), int(table_row["id"])),
        ).fetchone()
        incremental_mapping = connection.execute(
            """
            SELECT source_key, match_method, confidence, reason_code,
                   evidence_json, candidates_json, confirmed_by_user
            FROM report_incremental_table_mappings
            WHERE report_id = ? AND table_code = ?
            """,
            (int(report["id"]), str(table_row["code"])),
        ).fetchone()
        if generation is not None and str(generation["generation_status"]) in {
            "mapping_review", "new_table", "parse_review",
        }:
            status = TableStatus.NEEDS_REVIEW
            status_label = generation_status_label(str(generation["generation_status"]))
        update = connection.execute(
            """
            SELECT d.change_type, d.changed_cell_count
            FROM report_update_table_diffs d
            JOIN report_update_batches b ON b.id = d.batch_id
            WHERE b.report_id = ? AND d.report_table_id = ?
            ORDER BY b.id DESC LIMIT 1
            """,
            (int(report["id"]), int(table_row["id"])),
        ).fetchone()
        changes = []
        if update is not None and str(update["change_type"]) != "matching":
            changes.append(
                ChangeItem(
                    id=f"update-{table_row['id']}",
                    category="연보 업데이트",
                    item="변경된 표",
                    previous="기준 연보",
                    current=f"셀 {int(update['changed_cell_count'] or 0)}개 변경",
                    status="부분 검수 완료",
                )
            )

        return StatTable(
            id=table_id,
            code=table_row["code"],
            title=table_row["title"],
            title_en=part_title_en_from_table_row(table_row),
            section_title=table_row["section_title"],
            section_title_en=table_row["section_title_en"],
            domain=table_row["domain"],
            unit=table_row["unit"] or "-",
            sheet_name=table_row["section_file"],
            status=status,
            status_label=status_label,
            year_range=str(report["year"]),
            updated_at=date_only(table_row["extracted_at"]),
            theme=theme_from_code(table_row["code"]),
            part_label=part_label_from_table_row(table_row),
            hierarchy=build_hierarchy(table_row),
            columns=columns,
            rows=rows,
            summary=build_summary(table_row, rows, columns),
            key_figures=build_key_figures(table_row, rows, columns),
            checks=checks,
            changes=changes,
            visualizations=build_visualizations(table_id, table_row, rows, columns),
            metadata=TableMetadata(
                original_file=decode_display_text(report["source_file_name"]),
                sheet_name=table_row["section_file"],
                note="\n".join(
                    value
                    for value in (str(table_row["note"] or ""), *display_notes)
                    if value
                ),
                source=table_row["source"],
                source_department=str(table_row["source_department"] or contact.department),
                source_officer=str(table_row["source_officer"] or contact.officer),
                source_extension=str(table_row["source_extension"] or contact.extension),
                source_reference=str(table_row["source_reference"] or contact.source_reference),
                base_date=table_row["base_date"] or f"{report['year']} 기준",
                base_date_display=metadata_base_date_display(table_row, report["year"]),
                unit_display=metadata_unit_display(table_row),
                extracted_at=table_row["extracted_at"],
                header_count=header_count,
            ),
            generation_status=str(generation["generation_status"]) if generation else "",
            generation_status_label=(
                generation_status_label(str(generation["generation_status"]))
                if generation
                else ""
            ),
            generation_message=str(generation["generation_message"] or "") if generation else "",
            incremental_source_key=(
                str(incremental_mapping["source_key"] or "") if incremental_mapping else ""
            ),
            incremental_match_method=(
                str(incremental_mapping["match_method"] or "") if incremental_mapping else ""
            ),
            incremental_confidence=(
                float(incremental_mapping["confidence"] or 0) if incremental_mapping else 0
            ),
            incremental_reason_code=(
                str(incremental_mapping["reason_code"] or "") if incremental_mapping else ""
            ),
            incremental_evidence=(
                json_object(str(incremental_mapping["evidence_json"] or "{}"))
                if incremental_mapping
                else {}
            ),
            incremental_candidates=(
                json_object_list(str(incremental_mapping["candidates_json"] or "[]"))
                if incremental_mapping
                else []
            ),
            incremental_confirmed_by_user=(
                bool(incremental_mapping["confirmed_by_user"]) if incremental_mapping else False
            ),
            validation_stale=validation_stale,
        )

    def _latest_run_id(self, connection: DatabaseConnection, report_id: int) -> int | None:
        row = connection.execute(
            """
            SELECT id
            FROM validation_runs
            WHERE report_id = ?
            ORDER BY completed_at DESC, id DESC
            LIMIT 1
            """,
            (report_id,),
        ).fetchone()
        return int(row["id"]) if row else None


def table_summary(table: StatTable, *, validated_types: list[str] | None = None) -> StatTableSummary:
    return StatTableSummary(
        id=table.id,
        code=table.code,
        title=table.title,
        title_en=table.title_en,
        section_title=table.section_title,
        domain=table.domain,
        status=table.status,
        status_label=table.status_label,
        theme=table.theme,
        part_count=len(table.parts),
        summary=table.summary,
        key_figures=table.key_figures,
        checks=table.checks,
        validated_types=validated_types or [],
        is_test_table=table.is_test_table,
        generation_status=table.generation_status,
        generation_status_label=table.generation_status_label,
        generation_message=table.generation_message,
        incremental_source_key=table.incremental_source_key,
        incremental_match_method=table.incremental_match_method,
        incremental_confidence=table.incremental_confidence,
        incremental_reason_code=table.incremental_reason_code,
        incremental_evidence=table.incremental_evidence,
        incremental_candidates=table.incremental_candidates,
        incremental_confirmed_by_user=table.incremental_confirmed_by_user,
        update_mode=table.update_mode,
        source_dataset_title=table.source_dataset_title,
        validation_stale=table.validation_stale,
    )


def json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def json_object_list(value: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def chunks(values: list[int], size: int = 800) -> list[list[int]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def group_rows_by_int(rows: list[DatabaseRow], key: str) -> dict[int, list[DatabaseRow]]:
    grouped: dict[int, list[DatabaseRow]] = {}
    for row in rows:
        grouped.setdefault(int(row[key]), []).append(row)
    return grouped


def load_cells_by_table(
    connection: DatabaseConnection,
    table_ids: list[int],
) -> dict[int, list[DatabaseRow]]:
    rows: list[DatabaseRow] = []
    for chunk in chunks(table_ids):
        placeholders = ", ".join("?" for _ in chunk)
        rows.extend(
            connection.execute(
                f"""
                SELECT table_id, row_index, col_index, text_value, numeric_value, is_header, footnote_marker
                FROM stat_table_cells
                WHERE table_id IN ({placeholders})
                ORDER BY table_id, row_index, col_index
                """,
                chunk,
            ).fetchall()
        )
    return group_rows_by_int(rows, "table_id")


def load_checks_for_tables(
    connection: DatabaseConnection,
    run_id: int,
    table_ids: list[int],
    *,
    include_passing: bool = True,
) -> list[DatabaseRow]:
    rows: list[DatabaseRow] = []
    status_filter = "" if include_passing else "AND checks.status <> '정상'"
    for chunk in chunks(table_ids):
        placeholders = ", ".join("?" for _ in chunk)
        rows.extend(
            connection.execute(
                f"""
                SELECT checks.*
                FROM validation_checks AS checks
                JOIN stat_tables AS source_table ON source_table.id = checks.table_id
                JOIN validation_runs AS source_run ON source_run.id = checks.run_id
                WHERE checks.run_id = ? AND checks.table_id IN ({placeholders})
                  AND (
                    source_table.edited_after_run_id IS NULL
                    OR source_run.id > source_table.edited_after_run_id
                  )
                {status_filter}
                ORDER BY
                    checks.table_id,
                    CASE checks.status
                        WHEN '오류 의심' THEN 0
                        WHEN '확인 필요' THEN 1
                        WHEN '재검수 필요' THEN 1
                        WHEN '정상' THEN 2
                        ELSE 3
                    END,
                    CASE checks.severity
                        WHEN 'critical' THEN 0
                        WHEN 'warning' THEN 1
                        ELSE 2
                    END,
                    checks.row_index IS NULL,
                    checks.row_index,
                    checks.col_index,
                    checks.id
                """,
                [run_id, *chunk],
            ).fetchall()
        )
    return rows


def table_validation_is_stale(
    connection: DatabaseConnection,
    run_id: int | None,
    table_row: DatabaseRow,
) -> bool:
    edited_after_run_id = table_row["edited_after_run_id"]
    if edited_after_run_id is None:
        return False
    if run_id is None:
        return True
    return run_id <= int(edited_after_run_id)


def build_validation_issues(
    connection: DatabaseConnection,
    run_id: int | None,
    table_id: int,
    header_count: int,
    matrix: list[list[Any]] | None = None,
    *,
    check_rows: list[DatabaseRow] | None = None,
    specs_by_rule_id: dict[str, dict[str, Any]] | None = None,
    include_highlights: bool = True,
) -> list[ValidationIssue]:
    if run_id is None:
        return []

    if check_rows is None:
        check_rows = connection.execute(
            """
            SELECT *
            FROM validation_checks
            WHERE run_id = ? AND table_id = ?
            ORDER BY
                CASE status
                    WHEN '오류 의심' THEN 0
                    WHEN '확인 필요' THEN 1
                    WHEN '재검수 필요' THEN 1
                    WHEN '정상' THEN 2
                    ELSE 3
                END,
                CASE severity
                    WHEN 'critical' THEN 0
                    WHEN 'warning' THEN 1
                    ELSE 2
                END,
                row_index IS NULL,
                row_index,
                col_index,
                id
            """,
            (run_id, table_id),
        ).fetchall()

    specs_by_rule_id = specs_by_rule_id or load_rule_specs_by_id(connection, check_rows)
    return [
        validation_issue_from_row(
            row,
            issue_id=f"check-{row['id']}",
            check_type=row["check_type"],
            header_count=header_count,
            matrix=matrix,
            spec=specs_by_rule_id.get(row["rule_id"]),
            include_highlights=include_highlights,
        )
        for row in check_rows
    ]


def decode_display_text(value: str) -> str:
    decoded = unquote(value)
    return decoded or value


def status_from_checks(checks: list[ValidationIssue]) -> tuple[TableStatus, str]:
    active_checks = [check for check in checks if check.status != "정상"]
    if any(check.severity == "critical" for check in active_checks):
        return TableStatus.SUSPECTED_ERROR, "오류 의심"
    if any(check.status == "재검수 필요" for check in active_checks):
        return TableStatus.NEEDS_REVIEW, "재검수 필요"
    if active_checks:
        return TableStatus.NEEDS_REVIEW, "확인 필요"
    return TableStatus.NORMAL, "정상"


PART_SUFFIX_RE = re.compile(r"\s+표\s*(\d+)$")


def base_table_code(code: str) -> str:
    return PART_SUFFIX_RE.sub("", code)


def part_label_from_code(code: str) -> str | None:
    match = PART_SUFFIX_RE.search(code)
    return f"표{match.group(1)}" if match else None


def part_caption_from_raw_context(raw_context: str) -> tuple[str, str | None]:
    lines = [line.strip() for line in raw_context.splitlines() if line.strip()]
    caption_index = next(
        (index for index, line in enumerate(lines) if line.startswith(("▫", "※"))),
        None,
    )
    if caption_index is None:
        return "", None
    first_caption_line = lines[caption_index].lstrip("▫※").strip()
    # Legacy Markdown rows flatten the caption, base date, unit and first
    # header into one line.  Stop at the first metadata/header boundary.
    boundary = re.search(
        r"\s+(?=(?:\(\s*\d{4}[^)]*기준\)|\(\s*단위\s*:|"
        r"(?:구\s*분|연도|지역|국가|규\s*모)(?:\s*\n|\s*$)))",
        first_caption_line,
    )
    caption_was_trimmed = boundary is not None
    if boundary is not None:
        first_caption_line = first_caption_line[: boundary.start()].strip()
    caption_lines = [first_caption_line]
    if not caption_was_trimmed and caption_index + 1 < len(lines):
        next_line = lines[caption_index + 1]
        if re.search(r"[A-Za-z]", next_line) and not re.search(r"[가-힣]", next_line):
            caption_lines.append(next_line)
    caption = re.sub(r"\s+", " ", " ".join(caption_lines)).strip()
    caption = restore_hyphenated_line_breaks(caption)
    # Unit metadata can share the same HWPX paragraph as the visible part
    # caption.  Remove the paired Korean/English unit expressions before the
    # bilingual title split so ``Cities(Unit...)`` does not become a broken
    # English title such as ``Cities( (Unit...)``.
    caption = re.sub(
        r"\(\s*단위\s*:[^)]*\)\s*\(\s*Unit\s*:[^)]*\)\s*$",
        "",
        caption,
        flags=re.IGNORECASE,
    ).strip()
    title = clean_label(caption)
    title_en = english_label(caption)
    return title or caption, title_en


def part_label_from_table_row(table_row: DatabaseRow) -> str | None:
    base_label = part_label_from_code(table_row["code"])
    if not base_label:
        return None
    caption, _ = part_caption_from_raw_context(table_row["raw_context"] or "")
    return f"{base_label} · {caption}" if caption else base_label


def part_title_en_from_table_row(table_row: DatabaseRow) -> str:
    _, title_en = part_caption_from_raw_context(table_row["raw_context"] or "")
    return title_en or table_row["title_en"]


def part_title_from_label(part_label: str | None, fallback: str) -> str:
    if part_label and "·" in part_label:
        return part_label.split("·", 1)[1].strip()
    return fallback


def strip_part_suffix(value: str) -> str:
    return PART_SUFFIX_RE.sub("", value).strip()


def parent_code_for(code: str) -> str:
    base_code = base_table_code(code)
    if base_code.startswith("부록 "):
        match = re.match(r"^(부록\s+\d+)-\d+$", base_code)
        return match.group(1) if match else ""

    parts = base_code.split("-")
    return "-".join(parts[:-1]) if len(parts) > 1 else ""


def build_hierarchy(table_row: DatabaseRow) -> list[TableHierarchyItem]:
    base_code = base_table_code(table_row["code"])
    base_title = strip_part_suffix(table_row["title"])
    base_title_en = table_row["title_en"]
    hierarchy: list[TableHierarchyItem] = []

    domain = table_row["domain"]
    if domain and domain != "통계":
        hierarchy.append(TableHierarchyItem(code=base_code.split("-", 1)[0], title=domain))

    section_title = strip_part_suffix(table_row["section_title"] or "")
    if section_title and section_title != base_title:
        hierarchy.append(
            TableHierarchyItem(
                code=parent_code_for(base_code),
                title=section_title,
                title_en=table_row["section_title_en"] or None,
            )
        )

    hierarchy.append(TableHierarchyItem(code=base_code, title=base_title, title_en=base_title_en or None))
    return hierarchy


def table_to_part(table: StatTable) -> StatTablePart:
    return StatTablePart(
        id=table.id,
        code=table.code,
        title=part_title_from_label(table.part_label, strip_part_suffix(table.title)),
        title_en=table.title_en,
        part_label=table.part_label or "표",
        unit=table.unit,
        status=table.status,
        status_label=table.status_label,
        updated_at=table.updated_at,
        columns=table.columns,
        rows=table.rows,
        checks=table.checks,
        changes=table.changes,
        visualizations=table.visualizations,
        metadata=table.metadata,
        is_test_table=table.is_test_table,
        generation_status=table.generation_status,
        generation_status_label=table.generation_status_label,
        generation_message=table.generation_message,
        incremental_source_key=table.incremental_source_key,
        incremental_match_method=table.incremental_match_method,
        incremental_confidence=table.incremental_confidence,
        incremental_reason_code=table.incremental_reason_code,
        incremental_evidence=table.incremental_evidence,
        incremental_candidates=table.incremental_candidates,
        incremental_confirmed_by_user=table.incremental_confirmed_by_user,
        update_mode=table.update_mode,
        source_dataset_title=table.source_dataset_title,
        validation_stale=table.validation_stale,
    )


def group_title_en(table: StatTable) -> str:
    if table.hierarchy:
        title_en = table.hierarchy[-1].title_en
        if title_en:
            return title_en
    return table.title_en


def combined_status(tables: list[StatTable]) -> tuple[TableStatus, str]:
    if any(table.status == "suspected_error" for table in tables):
        return TableStatus.SUSPECTED_ERROR, "오류 의심"
    if any(table.status == "needs_review" for table in tables):
        return TableStatus.NEEDS_REVIEW, "확인 필요"
    if tables and all(table.status_label == "검수 전" for table in tables):
        return TableStatus.NORMAL, "검수 전"
    return TableStatus.NORMAL, "정상"


def group_table_parts(tables: list[StatTable]) -> list[StatTable]:
    grouped_tables: list[StatTable] = []
    groups: dict[str, list[StatTable]] = {}
    order: list[str] = []

    for table in tables:
        base_code = base_table_code(table.code)
        if base_code not in groups:
            groups[base_code] = []
            order.append(base_code)
        groups[base_code].append(table)

    for base_code in order:
        parts = groups[base_code]
        if len(parts) == 1:
            grouped_tables.append(parts[0])
            continue

        first = parts[0]
        status, status_label = combined_status(parts)
        combined_checks = [check for part in parts for check in part.checks]
        combined_changes = [change for part in parts for change in part.changes]
        combined_visualizations = [visualization for part in parts for visualization in part.visualizations]
        grouped_tables.append(
            first.model_copy(
                deep=True,
                update={
                    "id": f"group-{base_code}",
                    "code": base_code,
                    "title": strip_part_suffix(first.title),
                    "title_en": group_title_en(first),
                    "status": status,
                    "status_label": status_label,
                    "checks": combined_checks,
                    "changes": combined_changes,
                    "visualizations": combined_visualizations,
                    "parts": [table_to_part(part) for part in parts],
                    "validation_stale": any(part.validation_stale for part in parts),
                },
            )
        )

    return grouped_tables


def matrix_from_cells(cells: list[DatabaseRow]) -> list[list[str]]:
    if not cells:
        return []

    max_row = max(cell["row_index"] for cell in cells)
    max_col = max(cell["col_index"] for cell in cells)
    matrix = [["" for _ in range(max_col + 1)] for _ in range(max_row + 1)]

    for cell in cells:
        matrix[cell["row_index"]][cell["col_index"]] = cell["text_value"]

    return matrix


def footnote_matrix_from_cells(cells: list[DatabaseRow]) -> list[list[str]]:
    if not cells:
        return []

    max_row = max(cell["row_index"] for cell in cells)
    max_col = max(cell["col_index"] for cell in cells)
    matrix = [["" for _ in range(max_col + 1)] for _ in range(max_row + 1)]

    for cell in cells:
        matrix[cell["row_index"]][cell["col_index"]] = cell["footnote_marker"] or ""

    return matrix


def apply_display_matrix_repairs(
    table_code: str,
    matrix: list[list[str]],
    footnote_matrix: list[list[str]],
) -> list[str]:
    notes: list[str] = []
    if table_code == "4-1-9 표4":
        repair_local_government_sejong_eup_myeon_dong_column(matrix, footnote_matrix)
    normalize_flood_insurance_small_business_guide(table_code, matrix)
    spanning_note = detach_spanning_small_business_note(
        table_code,
        matrix,
        footnote_matrix,
    )
    if spanning_note:
        notes.append(spanning_note)
    return notes


def header_count_from_cells(cells: list[DatabaseRow], matrix: list[list[str]]) -> int:
    header_rows = {cell["row_index"] for cell in cells if cell["is_header"]}
    if header_rows:
        return display_header_count_from_matrix(matrix, max(header_rows) + 1)
    return display_header_count_from_matrix(matrix, 1 if matrix else 0)


def display_header_count_from_matrix(matrix: list[list[str]], stored_header_count: int) -> int:
    row_oriented_header_count = wide_row_oriented_text_table_header_count(matrix)
    if row_oriented_header_count is not None:
        return row_oriented_header_count
    header_count = stored_header_count
    max_header_count = min(len(matrix), 5)
    stored_header_rows = matrix[:stored_header_count]
    while header_count < max_header_count:
        candidate = matrix[header_count]
        if row_looks_like_blank_body_label_row(candidate, stored_header_rows):
            break
        if not row_looks_like_header_continuation(candidate):
            break
        header_count += 1
    return header_count


def row_looks_like_blank_body_label_row(row: list[str], header_rows: list[list[str]]) -> bool:
    """Detect body rows with empty measures before display-header expansion.

    Draft HWPX files often leave current-year measure cells blank.  Rows such
    as ``합계/총계`` or ``합계/광역`` then contain only label-column text and no
    numeric values, which made the display heuristic promote them into the
    header.  If the stored parser header already labels those leading columns,
    keep such rows in the body even when their measure cells are blank.
    """

    non_empty_positions = [
        col_index
        for col_index, cell in enumerate(row)
        if cell.strip()
    ]
    if len(non_empty_positions) < 2 or max(non_empty_positions) > 1:
        return False
    non_empty = [row[col_index].strip() for col_index in non_empty_positions]
    if any(parse_numeric(value) is not None for value in non_empty):
        return False
    return all(
        header_rows_cover_label_column(header_rows, col_index)
        for col_index in non_empty_positions
    )


def header_rows_cover_label_column(header_rows: list[list[str]], col_index: int) -> bool:
    if any(col_index < len(header_row) and header_row[col_index].strip() for header_row in header_rows):
        return True
    if col_index == 1:
        return any(header_row and looks_like_diagonal_region_classification_header(header_row[0]) for header_row in header_rows)
    return False


def looks_like_diagonal_region_classification_header(value: str) -> bool:
    normalized = re.sub(r"\s+", "", value).lower()
    return (
        ("지역" in normalized and "구분" in normalized)
        or ("region" in normalized and "classification" in normalized)
    )


def row_looks_like_header_continuation(row: list[str]) -> bool:
    non_empty = [cell.strip() for cell in row if cell.strip()]
    if len(non_empty) < 2:
        return False
    numeric_count = sum(1 for value in non_empty if parse_numeric(value) is not None)
    if numeric_count:
        return False
    joined = " ".join(non_empty).lower()
    has_header_keyword = bool(
        re.search(
            r"구분|분류|순위|국가명|지\s*수|지역|연도|항목|classification|ranking|country|index|year|total",
            joined,
        )
    )
    has_total_label = any(
        re.fullmatch(r"\s*계(?:\s*\n?\s*total)?\s*", value, re.IGNORECASE)
        for value in non_empty
    )
    return has_header_keyword or has_total_label


def row_is_caption_metadata(row: list[str]) -> bool:
    non_empty = [cell.strip() for cell in row if cell.strip()]
    if not non_empty:
        return False
    first = non_empty[0]
    return first.startswith("▫") or first.startswith("※")


# Include every apostrophe/prime glyph emitted by HWPX.  In particular, HWPX
# uses ``′`` for contractions in a few English translations (for example
# ``Resident′s Lawsuits``).  Leaving it out makes the glyph survive in the
# Korean label while disappearing from the English label.
ENGLISH_LABEL_BODY = r"A-Za-z0-9 /&().,%·･+=:\-'’‘′ʼ㎡㎢㎞㎏㎘㎖㎥→←↔"
ENGLISH_LABEL_SPAN_RE = re.compile(
    rf"\[\s*[A-Za-z][{ENGLISH_LABEL_BODY}]*\s*\]"
    rf"|\((?=[^)]*[A-Za-z]{{2}})(?=[^)]*\s)[{ENGLISH_LABEL_BODY}]+\)"
    rf"|(?<![A-Za-z0-9가-힣(/=+\-¤])(?:-\s*)?"
    rf"(?:\d[\d,]*(?:\.\d+)?(?:st|nd|rd|th)?(?:~\d+)?(?=\s+[A-Za-z])|\d+s|(?=[A-Za-z][{ENGLISH_LABEL_BODY}]*[A-Za-z])[A-Za-z])"
    rf"[{ENGLISH_LABEL_BODY}]*"
)
HEADER_FORMULA_RE = re.compile(
    r"(?<![A-Za-z])(?:"
    r"[A-Za-z]/\([A-Za-z](?:[+\-][A-Za-z])+\)"
    r"|[A-Za-z]\s*=\s*[A-Za-z](?:\s*[+\-]\s*[A-Za-z])+"
    r")(?![A-Za-z])"
)
KOREAN_TEMPORAL_DISPLAY_RE = re.compile(
    r"(?:\(\d+차\)\s*)?[’'‘]\d{2}\.\d{1,2}\.\d{1,2}\.?"
    r"(?:~\d{1,2}\.?)?(?:\s*\(\d+차\))?"
)
ENGLISH_TEMPORAL_DISPLAY_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?"
    r"\s+\d{1,2}(?:\s*[–-]\s*\d{1,2})?,?\s+\d{4}"
    r"(?:\s*\(#\d+\))?",
    re.IGNORECASE,
)


def pure_english_label_line_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or re.search(r"[가-힣]", stripped):
            continue
        if re.fullmatch(r"[A-Z]{2,}\)?", stripped) and index + 1 < len(lines):
            continue
        formula_candidate = stripped.strip("()[] ")
        if HEADER_FORMULA_RE.fullmatch(formula_candidate):
            continue
        if re.search(r"[A-Za-z]{2}", stripped):
            while index > 0 and re.fullmatch(r"\d{2,4}", lines[index - 1].strip()):
                index -= 1
            return index
    return None


def clean_label(text: str) -> str:
    restored = restore_hyphenated_line_breaks(text).replace("Classifi-cation", "Classification")
    lines = [line.strip() for line in restored.splitlines() if line.strip()]
    cleaned = re.sub(r"\s+", " ", " ".join(lines)).strip()
    if not cleaned:
        return ""

    formulas: list[str] = []
    korean_acronyms: list[str] = []
    leading_acronym = ""
    acronym_match = re.match(r"^([A-Z]{2,})\s+(?=[가-힣])", cleaned)
    if acronym_match:
        leading_acronym = acronym_match.group(1)
        cleaned = f"¤A¤{cleaned[acronym_match.end():]}"

    def protect_korean_acronym(match: re.Match[str]) -> str:
        value = match.group(0)
        normalized = re.sub(r"\s+", " ", value)
        normalized = re.sub(r"\(\s*/?\s*([A-Z]{2,})\s*\)", r"(\1)", normalized)
        if normalized not in korean_acronyms:
            korean_acronyms.append(normalized)
        return f"¤K{korean_acronyms.index(normalized)}¤"

    cleaned = re.sub(
        r"(?<=[가-힣])\(\s*/?\s*[A-Z]{2,}\s*\)",
        protect_korean_acronym,
        cleaned,
    )
    cleaned = re.sub(
        r"(?<=[가-힣])\s+[A-Z]{2,}(?=\s*\d*\s*[가-힣])",
        protect_korean_acronym,
        cleaned,
    )
    cleaned = re.sub(
        r"(?<=[가-힣·･])\s+([A-Z]{2,})(?=[ A-Za-z&]*\b\1\b)",
        protect_korean_acronym,
        cleaned,
    )
    cleaned = re.sub(
        r"(?<=[가-힣·･])([A-Z]{2,})(?=\s+[A-Za-z][ A-Za-z&]*\b\1\b)",
        protect_korean_acronym,
        cleaned,
    )

    def protect_formula(match: re.Match[str]) -> str:
        formula = re.sub(r"\s+", "", match.group(0))
        if formula not in formulas:
            formulas.append(formula)
        return f"¤{formulas.index(formula)}¤"

    protected = HEADER_FORMULA_RE.sub(protect_formula, cleaned)
    koreanish = ENGLISH_LABEL_SPAN_RE.sub("", protected)
    for formula_index, formula in enumerate(formulas):
        token = f"¤{formula_index}¤"
        first_index = koreanish.find(token)
        if first_index >= 0:
            tail = koreanish[first_index + len(token) :].replace(token, "")
            koreanish = koreanish[: first_index + len(token)] + tail
        koreanish = koreanish.replace(token, formula)
    for acronym_index, acronym in enumerate(korean_acronyms):
        koreanish = koreanish.replace(f"¤K{acronym_index}¤", acronym)
    if leading_acronym:
        koreanish = koreanish.replace("¤A¤", f"{leading_acronym} ")
    koreanish = re.sub(r"\s+", " ", koreanish).strip(" /")
    koreanish = re.sub(r"([･·])\s+([A-Z]{2,})$", r"\1\2", koreanish)
    koreanish = re.sub(r"\(\s+", "(", koreanish)
    koreanish = re.sub(r"\s+\)", ")", koreanish)
    koreanish = re.sub(r"(\([^()]+\))(?:\s+\1)+", r"\1", koreanish)
    if diagonal_region_header_label(koreanish, cleaned):
        return "지역"
    koreanish = re.sub(r"^구분(?=\S)", "구분 / ", koreanish)
    koreanish = koreanish.replace("()", "").strip(" /")
    koreanish = remove_unmatched_closing_parentheses(koreanish, preserve_numbered_markers=True)
    koreanish = re.sub(r"(\([^()]+\))(?:\s+\1)+", r"\1", koreanish)
    return koreanish or cleaned


def english_label(text: str) -> str | None:
    restored = restore_hyphenated_line_breaks(text).replace("Classifi-cation", "Classification")
    lines = [line.strip() for line in restored.splitlines() if line.strip()]
    english_line_index = pure_english_label_line_index(lines)
    english_source = lines[english_line_index:] if english_line_index is not None else lines
    if english_line_index is not None and english_line_index > 0 and english_source:
        acronym_prefix = re.match(r"^([A-Z]{2,})\s+(.+)$", english_source[0])
        if acronym_prefix and re.search(r"[･·]\s*$", lines[english_line_index - 1]):
            english_source = [acronym_prefix.group(2), *english_source[1:]]
    text = re.sub(r"\s+", " ", " ".join(english_source)).strip()
    if diagonal_region_header_label(clean_label_korean_only(restored), restored):
        return "Region"
    matches = ENGLISH_LABEL_SPAN_RE.findall(text)
    english_parts: list[str] = []
    for match in matches:
        item = match.strip()
        if not item:
            continue
        if english_parts and item.startswith(f"{english_parts[-1]} "):
            english_parts[-1] = item
        elif item not in english_parts:
            english_parts.append(item)
    value = " ".join(english_parts)
    value = HEADER_FORMULA_RE.sub(
        lambda match: re.sub(r"\s+", "", match.group(0)),
        value,
    )
    value = remove_unmatched_closing_parentheses(value)
    return value or None


def remove_unmatched_closing_parentheses(value: str, *, preserve_numbered_markers: bool = False) -> str:
    """Drop parser artifacts such as `Person)` while retaining balanced units and optional `1)` footnotes."""

    result: list[str] = []
    depth = 0
    for index, character in enumerate(value):
        if character == "(":
            depth += 1
            result.append(character)
            continue
        if character != ")":
            result.append(character)
            continue
        if depth:
            depth -= 1
            result.append(character)
            continue
        if preserve_numbered_markers and index > 0 and value[index - 1].isdigit():
            result.append(character)
    return re.sub(r"\s+", " ", "".join(result)).strip()


def clean_label_korean_only(text: str) -> str:
    cleaned = re.sub(
        r"\s+",
        " ",
        restore_hyphenated_line_breaks(text).replace("Classifi-cation", "Classification"),
    ).strip()
    koreanish = ENGLISH_LABEL_SPAN_RE.sub("", cleaned)
    return re.sub(r"\s+", " ", koreanish).strip(" /")


def diagonal_region_header_label(korean_text: str, raw_text: str) -> bool:
    normalized_korean = re.sub(r"\s+", "", korean_text)
    normalized_raw = raw_text.lower()
    return (
        "구분" in normalized_korean
        and "지역" in normalized_korean
        and "classification" in normalized_raw
        and "region" in normalized_raw
    )


def is_schedule_descriptor_column_label(value: str) -> bool:
    normalized = re.sub(r"[\s·,._\-()/%]+", "", value).lower()
    if any(keyword in normalized for keyword in ("운영일자", "일자", "일시", "날짜", "기간")):
        return True
    return bool(re.search(r"\b(dates?|period|schedule)\b", value, re.IGNORECASE))


def inherited_header_value(header_row: list[str], col_index: int) -> str:
    if col_index < len(header_row) and header_row[col_index].strip():
        return header_row[col_index]
    for left_col_index in range(col_index - 1, -1, -1):
        if left_col_index < len(header_row) and header_row[left_col_index].strip():
            return header_row[left_col_index]
    return ""


def header_text_for_column(matrix: list[list[str]], header_count: int, col_index: int) -> str:
    values = [
        row[col_index]
        for row in matrix[:header_count]
        if col_index < len(row) and row[col_index].strip()
    ]
    return " ".join(values)


def looks_like_year_label_column(matrix: list[list[str]], header_count: int, col_index: int, values: list[str]) -> bool:
    header = header_text_for_column(matrix, header_count, col_index).lower()
    if "연도" not in header and "year" not in header:
        return False
    if not values:
        return False
    year_like_count = sum(1 for value in values if re.fullmatch(r"[’']?\d{2,4}", value.strip()))
    return year_like_count / len(values) >= 0.7


def leading_label_column_indexes(matrix: list[list[str]], header_count: int) -> list[int]:
    data_rows = [row for row in matrix[header_count:] if any(cell.strip() for cell in row)]
    max_cols = max((len(row) for row in matrix), default=0)
    label_indexes: list[int] = []

    for col_index in range(max_cols):
        values = [
            row[col_index].strip()
            for row in data_rows
            if col_index < len(row) and row[col_index].strip()
        ]
        if not values:
            if label_indexes:
                label_indexes.append(col_index)
                continue
            break

        numeric_count = sum(1 for value in values if parse_numeric(value) is not None)
        numeric_ratio = numeric_count / len(values)
        header_text = header_text_for_column(matrix, header_count, col_index)
        if col_index == 0 and looks_like_year_label_column(matrix, header_count, col_index, values):
            label_indexes.append(col_index)
            continue
        if label_indexes and is_year_measure_column_label(header_text):
            break
        if label_indexes and is_schedule_descriptor_column_label(header_text):
            continue
        # A total measure can contain mostly '-' values (for example, a
        # grand total shown only on the subtotal row). It is still a numeric
        # column, not a second row-label dimension.
        if label_indexes and is_total_measure_column_label(header_text, values):
            break
        if label_indexes and is_measure_column_label(header_text):
            break
        if label_indexes and values_look_like_numeric_measure(values):
            break
        if numeric_ratio <= 0.25:
            label_indexes.append(col_index)
            continue
        break

    if independent_descriptor_label_columns(matrix, header_count, label_indexes):
        return [0]

    if len(label_indexes) > 3:
        return [0]

    if len(label_indexes) > 1:
        has_measure_column = any(
            any(
                col_index < len(row) and parse_numeric(row[col_index].strip()) is not None
                for row in data_rows
            )
            for col_index in range(label_indexes[-1] + 1, max_cols)
        )
        if not has_measure_column:
            return [0]

    return label_indexes or [0]


def is_year_measure_column_label(header_text: str) -> bool:
    normalized = re.sub(r"\s+", "", clean_label(header_text))
    return bool(re.fullmatch(r"(?:19|20)\d{2}(?:년(?:도)?)?", normalized))


def is_total_measure_column_label(header_text: str, values: list[str]) -> bool:
    if not any(parse_numeric(value) is not None for value in values):
        return False

    normalized = re.sub(r"\s+", "", header_text).lower()
    return (
        "전체" in header_text
        or "합계" in header_text
        or "총계" in header_text
        or "total" in normalized
        or bool(re.fullmatch(r"계(?:\([^)]*\))?", re.sub(r"\s+", "", header_text)))
    )


def is_measure_column_label(header_text: str) -> bool:
    normalized = re.sub(r"\s+", "", header_text).lower()
    return any(
        hint in normalized
        for hint in (
            "건수",
            "면적",
            "금액",
            "수량",
            "numberof",
            "number",
            "areas",
            "area",
            "amount",
            "재산",
            "인명",
            "property",
            "casualty",
        )
    )


def values_look_like_numeric_measure(values: list[str]) -> bool:
    if not values:
        return False
    numeric_count = sum(1 for value in values if parse_numeric(value) is not None)
    numeric_or_dash_count = sum(
        1
        for value in values
        if parse_numeric(value) is not None or value.strip() in {"-", "－", "―"}
    )
    return numeric_count >= 1 and numeric_or_dash_count / len(values) >= 0.7


def independent_descriptor_label_columns(
    matrix: list[list[str]],
    header_count: int,
    label_indexes: list[int],
) -> bool:
    """Keep registry-style text dimensions as columns instead of a hierarchical row path."""

    if len(label_indexes) < 2:
        return False
    descriptor_hints = (
        "위원회명",
        "설치근거",
        "설립근거",
        "위원장",
        "기관명",
        "기관장",
        "대표자",
        "소재지",
        "주소",
        "주요기능",
        "주요업무",
    )
    headers = [
        re.sub(r"\s+", "", header_text_for_column(matrix, header_count, col_index))
        for col_index in label_indexes
    ]
    normalized_headers = [header.lower() for header in headers]

    def contains(index: int, *hints: str) -> bool:
        return index < len(normalized_headers) and any(
            hint.lower() in normalized_headers[index] for hint in hints
        )

    # These are parallel source dimensions, not levels of one row label.
    # Keep the rule semantic so the same layout works for newly added tables.
    if len(headers) >= 2:
        if (
            contains(0, "연도", "year")
            and contains(1, "구분", "분류", "classification")
        ) or (
            contains(1, "연도", "year")
            and contains(0, "구분", "분류", "classification")
        ):
            return True
        if contains(0, "구분", "분류", "classification") and contains(1, "단위", "unit"):
            return True
        if contains(0, "지역", "region") and contains(
            1,
            "시･군･구",
            "시·군·구",
            "시군구",
            "cities",
            "counties",
            "districts",
        ):
            return True
        if contains(0, "지역", "region") and contains(1, "유형", "type"):
            return True
        if contains(0, "생산(이관)기관", "생산기관", "instruments of production") and contains(
            1,
            "기록물분야",
            "record subjects",
        ):
            return True
    # A service name and its description are parallel text dimensions. They
    # must remain separate columns even though both happen to be non-numeric.
    if any("서비스내용" in header or "servicedescription" in header.lower() for header in headers[1:]):
        return True
    return sum(any(hint in header for hint in descriptor_hints) for header in headers) >= 2


def label_path_for_row(row: list[str], label_column_indexes: list[int], target_col_index: int) -> str:
    parts: list[str] = []
    for col_index in label_column_indexes:
        if col_index > target_col_index or col_index >= len(row):
            continue
        label = clean_label_for_label_path(row[col_index], split_label_columns=len(label_column_indexes) > 1)
        if label and label not in parts:
            parts.append(label)
    return " / ".join(parts)


def clean_label_for_label_path(value: str, *, split_label_columns: bool) -> str:
    if (
        split_label_columns
        and not re.search(r"[가-힣]", value)
        and re.search(r"[A-Za-z]", value)
        and parse_numeric(value) is None
    ):
        return ""
    return clean_label(value)


def english_label_path_for_row(row: list[str], label_column_indexes: list[int], target_col_index: int) -> str | None:
    parts: list[str] = []
    for col_index in label_column_indexes:
        if col_index > target_col_index or col_index >= len(row):
            continue
        label = english_label(row[col_index])
        if label and label not in parts:
            parts.append(label)
    return " / ".join(parts) if parts else None


def split_bilingual_display_value(value: str) -> tuple[str, str | None]:
    if (
        not value.strip()
        or parse_numeric(value) is not None
        or not re.search(r"[가-힣]", value)
        or not re.search(r"[A-Za-z]", value)
    ):
        return value, None
    temporal_value = split_temporal_bilingual_display_value(value)
    if temporal_value is not None:
        return temporal_value
    stacked_value = split_stacked_bilingual_display_value(value)
    if stacked_value is not None:
        return stacked_value
    label_en = english_label(value)
    if not label_en:
        return value, None
    return clean_label(value), label_en


def split_temporal_bilingual_display_value(value: str) -> tuple[str, str] | None:
    korean_parts = [
        re.sub(r"\s+", " ", part).strip()
        for part in KOREAN_TEMPORAL_DISPLAY_RE.findall(value)
        if part.strip()
    ]
    english_parts = [
        re.sub(r"\s+", " ", part).strip()
        for part in ENGLISH_TEMPORAL_DISPLAY_RE.findall(value)
        if part.strip()
    ]
    if not korean_parts or not english_parts:
        return None
    # A damage-description cell can contain one Korean/English date inside
    # much longer prose.  It is not a date cell; extracting just the two dates
    # silently discarded the actual damage details (notably 7-3-1-2 이태원
    # 사고).  Only apply the compact date presentation when no semantic text
    # remains after removing every temporal token.
    remainder = KOREAN_TEMPORAL_DISPLAY_RE.sub("", value)
    remainder = ENGLISH_TEMPORAL_DISPLAY_RE.sub("", remainder)
    remainder = re.sub(r"[\s#(),./~–-]+", "", remainder)
    if remainder:
        return None
    return " ".join(korean_parts), " ".join(english_parts)


def split_stacked_bilingual_display_value(value: str) -> tuple[str, str] | None:
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in restore_hyphenated_line_breaks(value).splitlines()
        if line.strip()
    ]
    english_line_index = pure_english_label_line_index(lines)
    if english_line_index is None or english_line_index <= 0:
        return None
    english_lines = lines[english_line_index:]
    if any(re.search(r"[가-힣]", line) for line in english_lines):
        return None
    korean_lines = lines[:english_line_index]
    # HWPX occasionally puts a Korean label's attached acronym at the start
    # of the following English line: ``대량재해･ / DVI Mass Disaster & DVI``.
    # The acronym belongs to the Korean label; keeping it in both fields made
    # DVI visibly duplicate.
    acronym_prefix = re.match(r"^([A-Z]{2,})\s+(.+)$", english_lines[0])
    if (
        acronym_prefix
        and korean_lines
        and re.search(r"[･·]\s*$", korean_lines[-1])
    ):
        korean_lines[-1] = f"{korean_lines[-1]}{acronym_prefix.group(1)}"
        english_lines[0] = acronym_prefix.group(2)
    korean = clean_label("\n".join(korean_lines))
    english = remove_unmatched_closing_parentheses(" ".join(english_lines))
    if not korean or not english:
        return None
    return korean, english


def inferred_label_column_text(
    matrix: list[list[str]],
    header_count: int,
    label_column_indexes: list[int],
    col_index: int,
) -> tuple[str, str | None]:
    if col_index not in label_column_indexes:
        return "", None

    for row in matrix[header_count:]:
        if col_index >= len(row) or not row[col_index].strip():
            continue
        label = label_path_for_row(row, label_column_indexes, col_index)
        if label:
            return label, english_label_path_for_row(row, label_column_indexes, col_index)
    return "", None


def should_collapse_label_columns(label_column_indexes: list[int]) -> bool:
    return len(label_column_indexes) > 1 and label_column_indexes == list(range(len(label_column_indexes)))


def split_bilingual_descriptor_column_pairs(
    matrix: list[list[str]],
    header_count: int,
) -> set[tuple[int, int]]:
    """Find Korean/English columns produced from one merged HWPX header."""

    max_cols = max((len(row) for row in matrix), default=0)
    data_rows = [row for row in matrix[header_count:] if any(cell.strip() for cell in row)]
    pairs: set[tuple[int, int]] = set()
    for left_col in range(max_cols - 1):
        right_col = left_col + 1
        if not header_text_for_column(matrix, header_count, left_col).strip():
            continue
        if header_text_for_column(matrix, header_count, right_col).strip():
            continue

        paired_values = 0
        bilingual_values = 0
        for row in data_rows:
            left = row[left_col].strip() if left_col < len(row) else ""
            right = row[right_col].strip() if right_col < len(row) else ""
            if not left or not right:
                continue
            paired_values += 1
            if (
                re.search(r"[가-힣]", left)
                and re.search(r"[A-Za-z]", right)
                and not re.search(r"[가-힣]", right)
                and parse_numeric(right) is None
            ):
                bilingual_values += 1

        if paired_values >= 3 and bilingual_values / paired_values >= 0.8:
            pairs.add((left_col, right_col))
    return pairs


def display_source_columns(
    matrix: list[list[str]],
    header_count: int,
    label_column_indexes: list[int],
) -> list[list[int]]:
    max_cols = max((len(row) for row in matrix), default=0)
    if should_collapse_label_columns(label_column_indexes):
        hidden_label_columns = set(label_column_indexes[1:])
        groups = [
            label_column_indexes if col_index == label_column_indexes[0] else [col_index]
            for col_index in range(max_cols)
            if col_index not in hidden_label_columns
        ]
    else:
        groups = [[col_index] for col_index in range(max_cols)]

    bilingual_pairs = split_bilingual_descriptor_column_pairs(matrix, header_count)
    merged_groups: list[list[int]] = []
    index = 0
    while index < len(groups):
        if (
            index + 1 < len(groups)
            and len(groups[index]) == 1
            and len(groups[index + 1]) == 1
            and (groups[index][0], groups[index + 1][0]) in bilingual_pairs
        ):
            merged_groups.append([groups[index][0], groups[index + 1][0]])
            index += 2
            continue
        merged_groups.append(groups[index])
        index += 1
    return merged_groups


def header_rows_for_labels(matrix: list[list[str]], header_count: int) -> list[list[str]]:
    return [row for row in matrix[:header_count] if not row_is_caption_metadata(row)]


def has_display_data(matrix: list[list[str]], header_count: int, col_index: int) -> bool:
    return any(
        col_index < len(row) and row[col_index].strip()
        for row in matrix[header_count:]
    )


def has_display_header(header_rows: list[list[str]], col_index: int) -> bool:
    return any(col_index < len(row) and row[col_index].strip() for row in header_rows)


def build_columns(
    matrix: list[list[str]],
    header_count: int,
    label_column_indexes: list[int] | None = None,
    table_code: str | None = None,
    footnote_matrix: list[list[str]] | None = None,
) -> list[ColumnDefinition]:
    if not matrix:
        return []

    header_rows = header_rows_for_labels(matrix, header_count) if header_count else []
    label_column_indexes = label_column_indexes or leading_label_column_indexes(matrix, header_count)
    columns: list[ColumnDefinition] = []

    for source_col_indexes in display_source_columns(matrix, header_count, label_column_indexes):
        col_index = source_col_indexes[0]
        if (
            not any(source_col in label_column_indexes for source_col in source_col_indexes)
            and not has_display_data(matrix, header_count, col_index)
            and not has_display_header(header_rows, col_index)
        ):
            continue
        label_parts: list[str] = []
        english_parts: list[str] = []
        inferred_label, inferred_label_en = ("", None) if len(source_col_indexes) > 1 else inferred_label_column_text(
            matrix,
            header_count,
            label_column_indexes,
            col_index,
        )
        for header_row in header_rows:
            for header_col_index in source_col_indexes:
                value = header_row[header_col_index] if header_col_index < len(header_row) else ""
                if not value.strip() and not inferred_label:
                    value = inherited_header_value(header_row, header_col_index)
                label = clean_label(value)
                if label and label not in label_parts:
                    label_parts.append(label)
                en = english_label(value)
                if en and en not in english_parts:
                    english_parts.append(en)

        label = " / ".join(label_parts) or inferred_label or f"열 {col_index + 1}"
        label_en = " / ".join(english_parts) if english_parts else inferred_label_en
        header_footnotes: list[str] = []
        for row_index in range(min(header_count, len(footnote_matrix or []))):
            for header_col_index in source_col_indexes:
                marker = (
                    footnote_matrix[row_index][header_col_index]
                    if footnote_matrix
                    and header_col_index < len(footnote_matrix[row_index])
                    else ""
                )
                for item in marker.split():
                    if item and item not in header_footnotes:
                        header_footnotes.append(item)
        columns.append(
            ColumnDefinition(
                key=f"c{col_index}",
                label=label,
                label_en=label_en,
                header_path=label_parts or [label],
                header_path_en=english_parts,
                align=column_alignment(col_index, label, label_en),
                width=column_width(col_index, label, label_en),
                source_col_index=col_index,
                source_col_indexes=source_col_indexes,
                footnote_marker=" ".join(header_footnotes),
            )
        )

    return columns


def column_alignment(col_index: int, label: str, label_en: str | None) -> str:
    combined = f"{label} {label_en or ''}"
    if col_index == 0:
        return "left"
    if is_schedule_descriptor_column_label(combined):
        return "center"
    return "right"


def column_width(col_index: int, label: str, label_en: str | None) -> str | None:
    combined = f"{label} {label_en or ''}"
    if col_index == 0:
        return "24%"
    if is_schedule_descriptor_column_label(combined):
        return "18%"
    return None


def build_rows(
    matrix: list[list[str]],
    columns: list[ColumnDefinition],
    header_count: int,
    footnote_matrix: list[list[str]] | None = None,
    label_column_indexes: list[int] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    label_column_indexes = label_column_indexes or leading_label_column_indexes(matrix, header_count)
    for matrix_row_index, source_row in enumerate(matrix[header_count:], start=header_count):
        if not any(cell for cell in source_row):
            continue

        row: dict[str, Any] = {}
        row["_row_index"] = matrix_row_index
        row["_row_label"] = label_path_for_row(
            source_row,
            label_column_indexes,
            label_column_indexes[-1] if label_column_indexes else 0,
        )
        row["_row_label_en"] = english_label_path_for_row(
            source_row,
            label_column_indexes,
            label_column_indexes[-1] if label_column_indexes else 0,
        ) or ""
        for column in columns:
            col_index = column.source_col_index if column.source_col_index is not None else int(column.key[1:])
            is_label_column = column.source_col_indexes == label_column_indexes
            is_bilingual_descriptor_column = (
                len(column.source_col_indexes) > 1 and not is_label_column
            )
            combined_value = ""
            if is_label_column:
                value = row["_row_label"]
            elif is_bilingual_descriptor_column:
                source_values = [
                    source_row[source_col]
                    for source_col in column.source_col_indexes
                    if source_col < len(source_row) and source_row[source_col].strip()
                ]
                combined_value = "\n".join(source_values)
                value = clean_label(combined_value) or (source_values[0] if source_values else "")
            else:
                value = source_row[col_index] if col_index < len(source_row) else ""
                value, label_en = split_bilingual_display_value(value)
                if label_en:
                    row[f"{column.key}_en"] = label_en
            row[column.key] = coerce_display_value(value)
            if is_label_column and row["_row_label_en"]:
                row[f"{column.key}_en"] = row["_row_label_en"]
            elif is_bilingual_descriptor_column:
                label_en = english_label(combined_value)
                if label_en:
                    row[f"{column.key}_en"] = label_en
            footnote = (
                footnote_matrix[matrix_row_index][col_index]
                if footnote_matrix and matrix_row_index < len(footnote_matrix) and col_index < len(footnote_matrix[matrix_row_index])
                else ""
            )
            if footnote:
                row[f"{column.key}_footnote"] = footnote
        rows.append(row)

    return rows


def coerce_display_value(value: str) -> str | int | float:
    cleaned = value.strip()
    numeric = parse_numeric(cleaned)
    if numeric is None:
        return cleaned
    if numeric.is_integer() and "." not in cleaned:
        return int(numeric)
    return numeric


def parse_numeric(value: str) -> float | None:
    cleaned = value.replace(",", "").replace("%", "").strip()
    if not cleaned or cleaned in {"-", "－", "―"}:
        return None
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", cleaned):
        return float(cleaned)
    return None


def formatted_value(value: Any, unit: str) -> str:
    if isinstance(value, int):
        body = f"{value:,}"
    elif isinstance(value, float):
        body = f"{value:,.1f}" if not value.is_integer() else f"{int(value):,}"
    else:
        body = str(value)

    return f"{body}{unit}" if unit and unit not in {"-", "%"} and isinstance(value, (int, float)) else body


def metadata_base_date_display(table_row: DatabaseRow, report_year: int) -> str:
    fallback = table_row["base_date"] or f"{report_year} 기준"
    if table_row["manually_edited_at"]:
        return fallback
    raw_context = re.sub(r"\s+", " ", table_row["raw_context"] or "")
    match = re.search(r"\(\s*([^()]*?기준)\s*\)\s*\(\s*(As of [^)]+)\s*\)", raw_context)
    if not match:
        return fallback
    korean, english = match.groups()
    return f"{korean.strip()}({english.strip()})"


def metadata_unit_display(table_row: DatabaseRow) -> str:
    fallback = table_row["unit"] or "-"
    if table_row["manually_edited_at"]:
        return fallback
    raw_context = re.sub(r"\s+", " ", table_row["raw_context"] or "")
    match = re.search(r"\(\s*단위\s*:\s*([^)]+?)\s*\)\s*\(\s*(Unit\s*:\s*[^)]+)\s*\)", raw_context)
    if not match:
        return fallback
    unit, english = match.groups()
    return f"{unit.strip()}({english.strip()})"


def build_summary(
    table_row: DatabaseRow,
    rows: list[dict[str, Any]],
    columns: list[ColumnDefinition],
) -> list[str]:
    unit = table_row["unit"] or ""
    summary = [
        f"{table_row['title']} 표는 {len(rows)}개 행과 {len(columns)}개 항목으로 구조화되었습니다.",
    ]

    if table_row["base_date"]:
        summary.append(f"기준일은 {table_row['base_date']}이며, 단위는 {unit or '원문 표기 기준'}입니다.")
    elif unit:
        summary.append(f"단위는 {unit}입니다.")

    first_row = rows[0] if rows else None
    numeric_items = numeric_values(first_row, columns) if first_row else []
    if first_row and numeric_items:
        row_label = str(first_row.get(columns[0].key, "첫 행"))
        metric_label, metric_value = numeric_items[0]
        summary.append(f"{row_label}의 {metric_label} 값은 {formatted_value(metric_value, unit)}입니다.")

    return summary


def build_key_figures(
    table_row: DatabaseRow,
    rows: list[dict[str, Any]],
    columns: list[ColumnDefinition],
) -> list[Metric]:
    unit = table_row["unit"] or ""
    first_row = rows[0] if rows else None
    items = numeric_values(first_row, columns) if first_row else []

    if not items:
        return [
            Metric(label="행 수", value=f"{len(rows):,}", caption="구조화 결과", tone="blue"),
            Metric(label="열 수", value=f"{len(columns):,}", caption="구조화 결과", tone="neutral"),
        ]

    metrics: list[Metric] = []
    for index, (label, value) in enumerate(items[:3]):
        metrics.append(
            Metric(
                label=label,
                value=formatted_value(value, unit),
                caption="첫 데이터 행 기준",
                tone=["blue", "green", "neutral"][index],
            )
        )
    return metrics


def numeric_values(
    row: dict[str, Any] | None,
    columns: list[ColumnDefinition],
) -> list[tuple[str, int | float]]:
    if not row:
        return []

    values: list[tuple[str, int | float]] = []
    for column in columns[1:]:
        value = row.get(column.key)
        if isinstance(value, (int, float)):
            values.append((column.label, value))
    return values


def build_visualizations(
    table_id: str,
    table_row: DatabaseRow,
    rows: list[dict[str, Any]],
    columns: list[ColumnDefinition],
) -> list[Visualization]:
    if len(columns) < 2:
        return []

    label_key = columns[0].key
    numeric_column = next(
        (
            column
            for column in columns[1:]
            if any(isinstance(row.get(column.key), (int, float)) for row in rows[:12])
        ),
        None,
    )
    if numeric_column is None:
        return []

    series = [
        VisualizationSeries(label=str(row.get(label_key, "")), value=float(row[numeric_column.key]))
        for row in rows
        if isinstance(row.get(numeric_column.key), (int, float)) and str(row.get(label_key, "")).strip()
    ][:8]

    if len(series) < 2:
        return []

    return [
        Visualization(
            id=f"{table_id}-rank",
            title=f"{numeric_column.label} 주요 항목",
            subtitle=table_row["title"],
            kind="rank",
            unit=table_row["unit"] or "",
            data=series,
        )
    ]


def theme_from_code(code: str) -> str:
    chapter = code.split("-", 1)[0]
    if chapter == "6":
        return "red"
    if chapter == "7":
        return "green"
    return "blue"


def date_only(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
    except ValueError:
        return value
