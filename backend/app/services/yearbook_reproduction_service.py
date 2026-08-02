from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
from typing import TypeVar
import unicodedata

from app.db.connection import DB_PATH, DatabaseConnection, DatabaseRow, connect
from app.db.schema import init_db
from app.models.yearbook_reproduction import (
    RecipeBootstrapResult,
    ReproductionBuildSummary,
    ReproductionPeriodRule,
    ReproductionReportOption,
    ReproductionSourceCandidate,
    ReproductionSummary,
    ReproductionTableAnalysis,
    YearbookReproductionOverview,
)


YEAR_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
TITLE_NOISE_PATTERN = re.compile(r"[^0-9a-z가-힣]")
SUPPORTED_AUTOMATIC_MATERIALIZERS = {
    "period_rows",
    "period_columns",
    "current_period_rows",
}
T = TypeVar("T")


@dataclass(frozen=True)
class SourceSnapshot:
    row: DatabaseRow
    periods: frozenset[str]
    values_by_period: dict[str, Counter[str]]
    labels: frozenset[str]


@dataclass(frozen=True)
class TableSnapshot:
    row: DatabaseRow
    header_values: tuple[str, ...]
    data_values: tuple[str, ...]
    first_column_data: tuple[str, ...]


@dataclass(frozen=True)
class RecipeDefinition:
    status: str
    source_dataset_id: int | None
    materializer: str
    config: dict[str, object]

    @property
    def source_dataset_ids(self) -> tuple[int, ...]:
        bindings = self.config.get("source_bindings", [])
        if not isinstance(bindings, list):
            bindings = []
        dataset_ids = [
            int(binding["dataset_id"])
            for binding in bindings
            if isinstance(binding, dict) and binding.get("dataset_id") is not None
        ]
        if not dataset_ids and self.source_dataset_id is not None:
            dataset_ids.append(self.source_dataset_id)
        return tuple(dict.fromkeys(dataset_ids))


class YearbookReproductionService:
    """Analyze how an immutable annual report can be rebuilt from source data."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path

    def overview(
        self,
        *,
        report_id: int | None = None,
        report_year: int | None = None,
    ) -> YearbookReproductionOverview:
        with connect(self._db_path) as connection:
            init_db(connection)
            reports = self._reports(connection)
            report = resolve_report(reports, report_id=report_id, report_year=report_year)
            if report is None:
                raise ValueError("재현 기준으로 사용할 연보가 없습니다.")

            target_year = int(report["year"]) - 1
            tables = self._table_snapshots(connection, int(report["id"]))
            table_target_years = {
                int(infer_period_rule(table, target_year)[0].target_period)
                for table in tables
            }
            sources = self._source_snapshots(connection, table_target_years)
            recipes = latest_recipes(
                connection,
                [str(table.row["code"]) for table in tables],
                effective_year=int(report["year"]),
            )
            analyses = [
                analyze_table(
                    table,
                    sources,
                    target_year=target_year,
                    recipe=recipes.get(str(table.row["code"])),
                )
                for table in tables
            ]
            latest_build, comparison_by_table = latest_build_for_report(
                connection,
                int(report["id"]),
            )
            if comparison_by_table:
                analyses = [
                    table.model_copy(
                        update=comparison_by_table.get(table.table_id, {})
                    )
                    for table in analyses
                ]
            summary = reproduction_summary(analyses)
            return YearbookReproductionOverview(
                report_id=int(report["id"]),
                report_year=int(report["year"]),
                report_title=str(report["title"]),
                target_data_period=str(target_year),
                summary=summary,
                latest_build=latest_build,
                available_reports=[
                    ReproductionReportOption(
                        id=int(row["id"]),
                        year=int(row["year"]),
                        title=str(row["title"]),
                        is_archived=bool(row["is_archived"]),
                    )
                    for row in reports
                ],
                tables=analyses,
            )

    def bootstrap_draft_recipes(self, *, report_id: int) -> RecipeBootstrapResult:
        overview = self.overview(report_id=report_id)
        inserted = 0
        updated = 0
        skipped = 0
        mapped = 0
        review_required = 0
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                for table in overview.tables:
                    existing = connection.execute(
                        """
                        SELECT id, status, source_report_id
                        FROM yearbook_table_recipes
                        WHERE table_code = ?
                        ORDER BY revision DESC, id DESC
                        LIMIT 1
                        """,
                        (table.code,),
                    ).fetchone()
                    if existing is not None and (
                        str(existing["status"]) != "draft"
                        or int(existing["source_report_id"] or 0) != overview.report_id
                    ):
                        skipped += 1
                        continue
                    config = {
                        "value_authority": "source_ledger",
                        "target_period_offset": (
                            int(table.period_rule.target_period) - overview.report_year
                        ),
                        "period_selection": table.period_rule.model_dump(),
                        "source_mapping": {
                            "status": table.mapping_status,
                            "method": table.match_method,
                            "confidence": table.confidence,
                            "candidates": [
                                candidate.model_dump() for candidate in table.candidates
                            ],
                        },
                    }
                    if existing is None:
                        cursor = connection.execute(
                            """
                            INSERT INTO yearbook_table_recipes (
                                table_code, revision, effective_from_year,
                                source_dataset_id, materializer, config_json, status,
                                source_report_id, source_table_id, notes
                            ) VALUES (?, 1, ?, ?, ?, ?, 'draft', ?, ?, ?)
                            """,
                            (
                                table.code,
                                overview.report_year,
                                table.source_dataset_id,
                                table.materializer,
                                json.dumps(config, ensure_ascii=False),
                                overview.report_id,
                                table.table_id,
                                table.reason,
                            ),
                        )
                        if cursor.lastrowid is None:
                            raise RuntimeError(
                                f"{table.code} 초안 레시피를 저장하지 못했습니다."
                            )
                        inserted += 1
                    else:
                        connection.execute(
                            """
                            UPDATE yearbook_table_recipes
                            SET source_dataset_id = ?, materializer = ?,
                                config_json = ?, source_table_id = ?, notes = ?
                            WHERE id = ?
                            """,
                            (
                                table.source_dataset_id,
                                table.materializer,
                                json.dumps(config, ensure_ascii=False),
                                table.table_id,
                                table.reason,
                                int(existing["id"]),
                            ),
                        )
                        updated += 1
                    if table.mapping_status == "mapped":
                        mapped += 1
                    else:
                        review_required += 1
        return RecipeBootstrapResult(
            report_id=overview.report_id,
            inserted=inserted,
            updated=updated,
            skipped=skipped,
            mapped=mapped,
            review_required=review_required,
        )

    def _reports(self, connection: DatabaseConnection) -> list[DatabaseRow]:
        return connection.execute(
            """
            SELECT id, year, title, is_archived
            FROM annual_reports
            ORDER BY year, is_archived, id DESC
            """
        ).fetchall()

    def _table_snapshots(
        self,
        connection: DatabaseConnection,
        report_id: int,
    ) -> list[TableSnapshot]:
        table_rows = connection.execute(
            """
            SELECT id, code, title, table_order, base_date
            FROM stat_tables
            WHERE report_id = ?
            ORDER BY table_order, id
            """,
            (report_id,),
        ).fetchall()
        if not table_rows:
            return []
        cells_by_table: dict[int, list[DatabaseRow]] = defaultdict(list)
        table_ids = [int(row["id"]) for row in table_rows]
        for id_chunk in chunks(table_ids):
            placeholders = ",".join("?" for _ in id_chunk)
            cell_rows = connection.execute(
                f"""
                SELECT table_id, row_index, col_index, text_value, is_header
                FROM stat_table_cells
                WHERE table_id IN ({placeholders})
                ORDER BY table_id, row_index, col_index
                """,
                id_chunk,
            ).fetchall()
            for cell in cell_rows:
                cells_by_table[int(cell["table_id"])].append(cell)

        snapshots: list[TableSnapshot] = []
        for table in table_rows:
            cells = cells_by_table[int(table["id"])]
            headers = tuple(
                str(cell["text_value"] or "")
                for cell in cells
                if bool(cell["is_header"])
            )
            data = tuple(
                str(cell["text_value"] or "")
                for cell in cells
                if not bool(cell["is_header"])
            )
            first_column = tuple(
                str(cell["text_value"] or "")
                for cell in cells
                if not bool(cell["is_header"]) and int(cell["col_index"]) == 0
            )
            snapshots.append(
                TableSnapshot(
                    row=table,
                    header_values=headers,
                    data_values=data,
                    first_column_data=first_column,
                )
            )
        return snapshots

    def _source_snapshots(
        self,
        connection: DatabaseConnection,
        target_years: set[int],
    ) -> list[SourceSnapshot]:
        dataset_rows = connection.execute(
            """
            SELECT id, external_id, title
            FROM statistical_datasets
            WHERE status = 'active'
            ORDER BY id
            """
        ).fetchall()
        periods_by_dataset: dict[int, set[str]] = defaultdict(set)
        values_by_dataset: dict[int, dict[str, Counter[str]]] = defaultdict(
            lambda: defaultdict(Counter)
        )
        for row in connection.execute(
            """
            SELECT dataset_id, period
            FROM statistical_values
            GROUP BY dataset_id, period
            """
        ):
            periods_by_dataset[int(row["dataset_id"])].add(str(row["period"]))

        year_patterns = [f"{year}%" for year in sorted(target_years)]
        if year_patterns:
            where_clause = " OR ".join("period LIKE ?" for _ in year_patterns)
            value_rows = connection.execute(
                f"""
                SELECT dataset_id, period, data_value, string_value
                FROM statistical_values
                WHERE {where_clause}
                """,
                year_patterns,
            )
        else:
            value_rows = []
        for row in value_rows:
            dataset_id = int(row["dataset_id"])
            period = str(row["period"])
            normalized = comparable_value(
                str(row["string_value"] or row["data_value"] or "")
            )
            if normalized:
                values_by_dataset[dataset_id][period][normalized] += 1

        labels_by_dataset: dict[int, set[str]] = defaultdict(set)
        item_rows = connection.execute(
            """
            SELECT dataset_id, item_name, full_name
            FROM statistical_dataset_items
            ORDER BY dataset_id, display_order, item_data_no
            """
        )
        for row in item_rows:
            dataset_id = int(row["dataset_id"])
            for raw_label in (row["item_name"], row["full_name"]):
                label = comparable_label(str(raw_label or ""))
                if label:
                    labels_by_dataset[dataset_id].add(label)

        return [
            SourceSnapshot(
                row=row,
                periods=frozenset(periods_by_dataset[int(row["id"])]),
                values_by_period=dict(values_by_dataset[int(row["id"])]),
                labels=frozenset(labels_by_dataset[int(row["id"])]),
            )
            for row in dataset_rows
        ]


def resolve_report(
    reports: list[DatabaseRow],
    *,
    report_id: int | None,
    report_year: int | None,
) -> DatabaseRow | None:
    if report_id is not None:
        return next((row for row in reports if int(row["id"]) == report_id), None)
    if report_year is not None:
        candidates = [row for row in reports if int(row["year"]) == report_year]
        active = next((row for row in candidates if not bool(row["is_archived"])), None)
        return active or (candidates[0] if candidates else None)
    active = [row for row in reports if not bool(row["is_archived"])]
    return active[-1] if active else (reports[-1] if reports else None)


def analyze_table(
    table: TableSnapshot,
    sources: list[SourceSnapshot],
    *,
    target_year: int,
    recipe: RecipeDefinition | None,
) -> ReproductionTableAnalysis:
    period_rule, materializer = infer_period_rule(table, target_year)
    if recipe is not None and recipe.status == "approved":
        configured_target = str(recipe.config.get("target_period") or "")
        if configured_target:
            period_rule = period_rule.model_copy(
                update={
                    "target_period": configured_target,
                    "anchor": "user_confirmed",
                }
            )
    table_target_year = int(period_rule.target_period)
    table_title = str(table.row["title"])
    if recipe is not None and recipe.status == "approved":
        confirmed_sources = [
            source
            for source in sources
            if int(source.row["id"]) in recipe.source_dataset_ids
        ]
        candidates = sorted(
            (
                candidate_projection(
                    table,
                    source,
                    target_year=table_target_year,
                    exact_title=False,
                )
                for source in confirmed_sources
            ),
            key=candidate_sort_key,
            reverse=True,
        )
        selected = next(
            (candidate for candidate in candidates if candidate.has_target_period),
            candidates[0] if candidates else None,
        )
        materializer = recipe.materializer or materializer
        is_copy = materializer == "copy"
        has_required_data = bool(selected and selected.has_target_period)
        basic_recipe = (
            (is_copy or materializer in SUPPORTED_AUTOMATIC_MATERIALIZERS)
            and (is_copy or has_required_data)
        )
        source_titles = [str(source.row["title"]) for source in confirmed_sources]
        reason = (
            "사용자가 확정한 원장 연결입니다."
            if basic_recipe
            else (
                "사용자가 원장 연결을 확정했지만 표시 기준기간의 원장값이 없습니다."
                if selected is not None
                else "사용자가 확정한 원장 연결 정보를 찾지 못했습니다."
            )
        )
        return ReproductionTableAnalysis(
            table_id=int(table.row["id"]),
            code=str(table.row["code"]),
            title=table_title,
            table_order=int(table.row["table_order"]),
            mapping_status="mapped" if is_copy or selected is not None else "unmapped",
            generation_status="basic_recipe" if basic_recipe else "custom_recipe",
            materializer=materializer,
            source_dataset_id=selected.dataset_id if selected is not None else None,
            source_external_id=selected.external_id if selected is not None else "",
            source_title=", ".join(source_titles),
            match_method="user_confirmed",
            confidence=1.0,
            reason=reason,
            period_rule=period_rule,
            candidates=candidates,
            recipe_status=recipe.status,
        )

    normalized_title = comparable_label(table_title)
    exact = [
        source
        for source in sources
        if comparable_label(str(source.row["title"])) == normalized_title
    ]
    match_method = "normalized_title"
    source_candidates = exact
    if not source_candidates:
        match_method = "title_similarity"
        ranked = sorted(
            (
                (
                    SequenceMatcher(
                        None,
                        normalized_title,
                        comparable_label(str(source.row["title"])),
                    ).ratio(),
                    source,
                )
                for source in sources
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        source_candidates = [source for score, source in ranked[:3] if score >= 0.70]

    candidates = sorted(
        (
            candidate_projection(
                table,
                source,
                target_year=table_target_year,
                exact_title=source in exact,
            )
            for source in source_candidates
        ),
        key=candidate_sort_key,
        reverse=True,
    )
    selected, mapping_status, reason = select_candidate(candidates, exact_count=len(exact))
    has_required_data = bool(selected and selected.has_target_period)
    basic_recipe = (
        mapping_status == "mapped"
        and materializer in SUPPORTED_AUTOMATIC_MATERIALIZERS
        and has_required_data
    )
    generation_status = "basic_recipe" if basic_recipe else "custom_recipe"
    if selected is None:
        confidence = 0
    else:
        confidence = candidate_confidence(selected, exact_title=match_method == "normalized_title")

    return ReproductionTableAnalysis(
        table_id=int(table.row["id"]),
        code=str(table.row["code"]),
        title=table_title,
        table_order=int(table.row["table_order"]),
        mapping_status=mapping_status,
        generation_status=generation_status,
        materializer=materializer,
        source_dataset_id=selected.dataset_id if selected and mapping_status == "mapped" else None,
        source_external_id=selected.external_id if selected and mapping_status == "mapped" else "",
        source_title=selected.title if selected and mapping_status == "mapped" else "",
        match_method=match_method if candidates else "",
        confidence=confidence,
        reason=reason,
        period_rule=period_rule,
        candidates=candidates,
        recipe_status=recipe.status if recipe is not None else "",
    )


def candidate_projection(
    table: TableSnapshot,
    source: SourceSnapshot,
    *,
    target_year: int,
    exact_title: bool,
) -> ReproductionSourceCandidate:
    source_title = str(source.row["title"])
    title_similarity = SequenceMatcher(
        None,
        comparable_label(str(table.row["title"])),
        comparable_label(source_title),
    ).ratio()
    selected_period = preferred_period(source.periods, target_year)
    source_values = source.values_by_period.get(selected_period, Counter())
    table_values = Counter(
        value
        for raw in table.data_values
        if (value := comparable_value(raw))
    )
    value_coverage = counter_coverage(source_values, table_values, ignore_zero=True)
    table_headers = {
        label for raw in table.header_values if (label := comparable_label(raw))
    }
    header_coverage = set_coverage(source.labels, table_headers)
    return ReproductionSourceCandidate(
        dataset_id=int(source.row["id"]),
        external_id=str(source.row["external_id"]),
        title=source_title,
        title_similarity=round(1.0 if exact_title else title_similarity, 4),
        value_coverage=round(value_coverage, 4),
        header_coverage=round(header_coverage, 4),
        has_target_period=bool(selected_period),
    )


def select_candidate(
    candidates: list[ReproductionSourceCandidate],
    *,
    exact_count: int,
) -> tuple[ReproductionSourceCandidate | None, str, str]:
    if not candidates:
        return None, "unmapped", "제목과 연결되는 원장 통계를 찾지 못했습니다."
    if exact_count == 1:
        selected = candidates[0]
        if selected.has_target_period:
            return selected, "mapped", "정규화된 제목이 일치하는 원장 통계입니다."
        return (
            selected,
            "mapped",
            "제목은 일치하지만 기준연도 원장값이 없어 기간 또는 원천 확인이 필요합니다.",
        )
    if exact_count > 1:
        best = candidates[0]
        runner_up = candidates[1]
        value_margin = best.value_coverage - runner_up.value_coverage
        if (
            best.has_target_period
            and (
                (best.value_coverage >= 0.60 and value_margin >= 0.10)
                or (
                    not runner_up.has_target_period
                    and best.value_coverage > runner_up.value_coverage
                )
            )
        ):
            return (
                best,
                "mapped",
                "동일 제목 후보 중 기존 연보 셀과의 값 일치율로 원장을 식별했습니다.",
            )
        return (
            None,
            "review",
            "같은 제목의 원장 통계가 여러 개라 후보 확인이 필요합니다.",
        )
    best = candidates[0]
    runner_up = candidates[1] if len(candidates) > 1 else None
    runner_score = (
        runner_up.value_coverage * 0.75 + runner_up.header_coverage * 0.25
        if runner_up is not None
        else 0
    )
    best_score = best.value_coverage * 0.75 + best.header_coverage * 0.25
    if (
        best.title_similarity >= 0.72
        and best.value_coverage >= 0.85
        and (best.header_coverage >= 0.20 or best.title_similarity >= 0.80)
        and best.has_target_period
        and (
            runner_up is None
            or not runner_up.has_target_period
            or best_score - runner_score >= 0.20
        )
    ):
        return (
            best,
            "mapped",
            "유사 제목 후보 중 기준기간 값과 항목 일치율로 원장을 식별했습니다.",
        )
    return (
        None,
        "review",
        "유사 제목 후보는 찾았지만 자동 확정하지 않았습니다.",
    )


def infer_period_rule(
    table: TableSnapshot,
    target_year: int,
) -> tuple[ReproductionPeriodRule, str]:
    allowed_ceiling = target_year + 1
    row_years = ordered_years(table.first_column_data, allowed_ceiling)
    if len(row_years) >= 2:
        selected_target = max(row_years)
        return (
            ReproductionPeriodRule(
                mode="latest_n",
                count=len(row_years),
                first_period=str(row_years[0]),
                last_period=str(row_years[-1]),
                target_period=str(selected_target),
                anchor="displayed_last_period",
            ),
            "period_rows",
        )
    header_years = ordered_years(table.header_values, allowed_ceiling)
    if len(header_years) >= 2:
        selected_target = max(header_years)
        return (
            ReproductionPeriodRule(
                mode="latest_n",
                count=len(header_years),
                first_period=str(header_years[0]),
                last_period=str(header_years[-1]),
                target_period=str(selected_target),
                anchor="displayed_last_period",
            ),
            "period_columns",
        )
    base_date_years = ordered_years((str(table.row["base_date"] or ""),), allowed_ceiling)
    selected_target = base_date_years[-1] if base_date_years else target_year
    return (
        ReproductionPeriodRule(
            mode="single_period",
            count=1,
            first_period=str(selected_target),
            last_period=str(selected_target),
            target_period=str(selected_target),
            anchor="base_date" if base_date_years else "report_year_minus_1",
        ),
        "current_period_rows",
    )


def reproduction_summary(
    analyses: list[ReproductionTableAnalysis],
) -> ReproductionSummary:
    mapped = sum(table.mapping_status == "mapped" for table in analyses)
    review = sum(table.mapping_status == "review" for table in analyses)
    unmapped = sum(table.mapping_status == "unmapped" for table in analyses)
    basic_recipe = sum(table.generation_status == "basic_recipe" for table in analyses)
    return ReproductionSummary(
        total_tables=len(analyses),
        mapped_tables=mapped,
        review_tables=review,
        unmapped_tables=unmapped,
        basic_recipe_candidates=basic_recipe,
        custom_recipe_required=len(analyses) - basic_recipe,
        draft_recipes=sum(table.recipe_status == "draft" for table in analyses),
    )


def latest_recipes(
    connection: DatabaseConnection,
    table_codes: list[str],
    *,
    effective_year: int,
) -> dict[str, RecipeDefinition]:
    if not table_codes:
        return {}
    result: dict[str, RecipeDefinition] = {}
    for code_chunk in chunks(table_codes):
        placeholders = ",".join("?" for _ in code_chunk)
        rows = connection.execute(
            f"""
            SELECT table_code, status, revision, source_dataset_id,
                   materializer, config_json
            FROM yearbook_table_recipes
            WHERE table_code IN ({placeholders})
              AND effective_from_year <= ?
              AND (effective_to_year IS NULL OR effective_to_year >= ?)
            ORDER BY table_code, revision DESC
            """,
            [*code_chunk, effective_year, effective_year],
        ).fetchall()
        for row in rows:
            code = str(row["table_code"])
            if code in result:
                continue
            try:
                config = json.loads(str(row["config_json"] or "{}"))
            except json.JSONDecodeError:
                config = {}
            result[code] = RecipeDefinition(
                status=str(row["status"]),
                source_dataset_id=(
                    int(row["source_dataset_id"])
                    if row["source_dataset_id"] is not None
                    else None
                ),
                materializer=str(row["materializer"] or ""),
                config=config if isinstance(config, dict) else {},
            )
    return result


def latest_build_for_report(
    connection: DatabaseConnection,
    report_id: int,
) -> tuple[ReproductionBuildSummary | None, dict[int, dict[str, object]]]:
    run = connection.execute(
        """
        SELECT *
        FROM yearbook_reproduction_runs
        WHERE baseline_report_id = ? AND status = 'completed'
        ORDER BY completed_at DESC, id DESC
        LIMIT 1
        """,
        (report_id,),
    ).fetchone()
    if run is None:
        return None, {}
    summary = json.loads(str(run["summary_json"] or "{}"))
    build = ReproductionBuildSummary(
        id=int(run["id"]),
        report_id=int(run["baseline_report_id"]),
        report_year=int(run["report_year"]),
        target_data_year=int(run["target_data_year"]),
        status=str(run["status"]),
        created_at=str(run["created_at"] or ""),
        completed_at=str(run["completed_at"] or ""),
        **summary,
    )
    result_rows = connection.execute(
        """
        SELECT baseline_table_id, status, compared_cell_count,
               mismatch_count, error_message
        FROM yearbook_reproduction_table_results
        WHERE run_id = ?
        """,
        (int(run["id"]),),
    ).fetchall()
    return build, {
        int(row["baseline_table_id"]): {
            "comparison_status": str(row["status"]),
            "compared_cell_count": int(row["compared_cell_count"] or 0),
            "mismatch_count": int(row["mismatch_count"] or 0),
            "comparison_error": str(row["error_message"] or ""),
        }
        for row in result_rows
    }


def preferred_period(periods: frozenset[str], target_year: int) -> str:
    preferred = f"{target_year}00"
    if preferred in periods:
        return preferred
    matches = sorted(period for period in periods if period.startswith(str(target_year)))
    return matches[-1] if matches else ""


def candidate_sort_key(candidate: ReproductionSourceCandidate) -> tuple[float, ...]:
    evidence = (
        candidate.value_coverage * 0.55
        + candidate.header_coverage * 0.25
        + candidate.title_similarity * 0.20
    )
    return (
        float(candidate.has_target_period),
        evidence,
        candidate.value_coverage,
        candidate.header_coverage,
        candidate.title_similarity,
    )


def candidate_confidence(
    candidate: ReproductionSourceCandidate,
    *,
    exact_title: bool,
) -> float:
    title_weight = 0.55 if exact_title else 0.35
    score = (
        title_weight * candidate.title_similarity
        + 0.30 * candidate.value_coverage
        + 0.10 * candidate.header_coverage
        + 0.05 * float(candidate.has_target_period)
    )
    return round(min(1.0, score), 4)


def ordered_years(values: tuple[str, ...], target_year: int) -> list[int]:
    output: list[int] = []
    seen: set[int] = set()
    for raw in values:
        match = YEAR_PATTERN.search(first_display_line(raw))
        if match is None:
            continue
        year = int(match.group(1))
        if year > target_year or year in seen:
            continue
        output.append(year)
        seen.add(year)
    return output


def counter_coverage(
    source: Counter[str],
    target: Counter[str],
    *,
    ignore_zero: bool,
) -> float:
    filtered = Counter(source)
    if ignore_zero:
        filtered.pop("n:0", None)
    total = sum(filtered.values())
    if total == 0:
        return 0
    overlap = sum(min(count, target.get(value, 0)) for value, count in filtered.items())
    return overlap / total


def set_coverage(source: frozenset[str], target: set[str]) -> float:
    if not source:
        return 0
    return len(source & target) / len(source)


def comparable_value(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    numeric_text = text.replace(",", "").replace("−", "-").replace("－", "-")
    try:
        numeric = Decimal(numeric_text)
    except InvalidOperation:
        label = comparable_label(text)
        return f"t:{label}" if label else ""
    return f"n:{format(numeric.normalize(), 'f')}"


def comparable_label(value: str) -> str:
    line = first_display_line(value)
    normalized = unicodedata.normalize("NFKC", line).lower()
    return TITLE_NOISE_PATTERN.sub("", normalized)


def first_display_line(value: str) -> str:
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    if not lines:
        return ""
    korean = next((line for line in lines if re.search(r"[가-힣]", line)), None)
    return korean or lines[0]


def chunks(values: list[T], size: int = 700) -> list[list[T]]:
    return [values[index : index + size] for index in range(0, len(values), size)]
