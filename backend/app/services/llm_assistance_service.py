"""Opt-in LLM assistance around deterministic report workflows.

The LLM never replaces the existing parser, matcher, or rule engine.  It only
receives records that those systems could not settle.  Every response is a
schema-constrained plan; local validation decides whether a small, reversible
interpretation can be applied or must remain a proposal for review.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

from app.core.llm_client import (
    ResponsesTransport,
    parse_responses_json,
    resolve_llm_client_settings,
)
from app.db.connection import DB_PATH, DatabaseConnection, connect
from app.db.schema import init_db


DecisionProvider = Callable[[str, dict[str, Any]], dict[str, Any]]
PROMPT_VERSION = "report-assistance-v1"


IMPORT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "table_id": {"type": "integer"},
                    "action": {
                        "type": "string",
                        "enum": ["interpret", "review", "no_change"],
                    },
                    "header_row_count": {"type": ["integer", "null"]},
                    "unit": {"type": "string"},
                    "base_date": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string"},
                },
                "required": [
                    "table_id", "action", "header_row_count", "unit",
                    "base_date", "confidence", "reason",
                ],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["decisions", "notes"],
    "additionalProperties": False,
}


INCREMENT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target_key": {"type": "string"},
                    "table_code": {"type": "string"},
                    "source_key": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": ["connect", "new_statistic", "keep_review"],
                    },
                    "update_mode": {
                        "type": "string",
                        "enum": [
                            "existing_cells", "time_rows", "grouped_time_rows",
                            "time_columns", "snapshot", "split_tables", "unknown",
                        ],
                    },
                    "retention_mode": {
                        "type": "string",
                        "enum": ["rolling_window", "append_history", "replace", "unknown"],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string"},
                },
                "required": [
                    "target_key", "table_code", "source_key", "action",
                    "update_mode", "retention_mode", "confidence", "reason",
                ],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["decisions", "notes"],
    "additionalProperties": False,
}


class ReportLLMAssistanceService:
    """Run optional interpretation only after deterministic handling."""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        *,
        decision_provider: DecisionProvider | None = None,
        model: str = "gpt-5-mini",
    ) -> None:
        self._db_path = db_path
        self._decision_provider = decision_provider
        self._settings = resolve_llm_client_settings(
            openai_model=model,
            bizrouter_model=f"openai/{model}",
        )

    def assist_import(self, report_id: int) -> dict[str, object]:
        """Interpret only tables for which deterministic parsing left evidence."""
        with connect(self._db_path) as connection:
            init_db(connection)
            candidates = import_candidates(connection, report_id)
        if not candidates:
            return assistance_result("full_import", available=self.available, candidates=0)
        if not self.available:
            result = assistance_result(
                "full_import",
                available=False,
                candidates=len(candidates),
                message=f"{self._settings.api_key_env}가 없어 기존 파싱 결과를 유지했습니다.",
            )
            self._sync_unresolved_import_reviews(report_id, candidates)
            return result
        try:
            decision = self._request(
                "full_import",
                {
                "prompt_version": PROMPT_VERSION,
                "tables": candidates,
                "instructions": (
                    "기존 파서가 경고를 남긴 표만 해석한다. 원문에 보이는 행만 헤더로 지정하고 "
                    "값이나 행·열을 생성하지 않는다. unit/base_date는 현재 값이 비어 있고 표 안에 "
                    "명시된 경우만 제안한다. 불확실하면 review를 선택한다."
                ),
                },
                IMPORT_RESPONSE_SCHEMA,
            )
        except Exception as error:
            result = assistance_result(
                "full_import", available=True, candidates=len(candidates),
                message=f"LLM 보조 해석에 실패하여 기존 파싱 결과를 유지했습니다: {str(error)[:200]}",
            )
            self._sync_unresolved_import_reviews(report_id, candidates)
            return result
        try:
            result = self._apply_import_decisions(report_id, candidates, decision)
        except Exception as error:
            result = assistance_result(
                "full_import", available=True, candidates=len(candidates),
                message=f"LLM 해석안 검증에 실패하여 기존 파싱 결과를 유지했습니다: {str(error)[:200]}",
            )
        self._sync_unresolved_import_reviews(report_id, candidates)
        return result

    def assist_increment(self, report_id: int) -> dict[str, object]:
        """Suggest connections for review/unmatched increments, then revalidate."""
        with connect(self._db_path) as connection:
            init_db(connection)
            candidates = increment_candidates(connection, report_id)
        if not candidates:
            return assistance_result("increment", available=self.available, candidates=0)
        if not self.available:
            return assistance_result(
                "increment",
                available=False,
                candidates=len(candidates),
                message=f"{self._settings.api_key_env}가 없어 기존 증분 판정을 유지했습니다.",
            )
        try:
            decision = self._request(
                "increment",
                {
                "prompt_version": PROMPT_VERSION,
                "items": candidates,
                "instructions": (
                    "M키는 데이터 식별자이고 표 번호는 연보 표시 번호다. 제목, 메타정보, 헤더 경로, "
                    "행 라벨과 연도 축을 함께 보고 동일 통계를 판단한다. 새 통계·분리 표·불확실한 "
                    "항목은 자동 연결하지 말고 new_statistic 또는 keep_review를 선택한다."
                ),
                },
                INCREMENT_RESPONSE_SCHEMA,
            )
        except Exception as error:
            return assistance_result(
                "increment", available=True, candidates=len(candidates),
                message=f"LLM 증분 해석에 실패하여 기존 연결 결과를 유지했습니다: {str(error)[:200]}",
            )
        try:
            return self._apply_increment_decisions(report_id, candidates, decision)
        except Exception as error:
            return assistance_result(
                "increment", available=True, candidates=len(candidates),
                message=f"LLM 연결안 검증에 실패하여 기존 증분 결과를 유지했습니다: {str(error)[:200]}",
            )

    def assist_profile_drafts(self, report_id: int) -> dict[str, object]:
        """Prepare only uncertain calculation profiles for an optional LLM pass.

        A full-report upload creates a draft before any validation run exists.
        Running this small preflight lets the upload option cover both parser
        interpretation and profile preparation, without creating validation
        results or changing a table's validation status.
        """

        try:
            from app.validation.profile_repository import ValidationProfileRepository
            from app.validation.profiles import GPTProfileDraftProvider, HeuristicProfileDraftProvider
            from app.validation.repository import ValidationRepository

            tables = ValidationRepository(self._db_path).load_tables(report_id)
            if not tables:
                return assistance_result("validation_profile", available=self.available, candidates=0)

            repository = ValidationProfileRepository(self._db_path)
            baseline = repository.ensure_profiles(
                report_id=report_id,
                tables=tables,
                provider=HeuristicProfileDraftProvider(),
            )
            candidate_codes = {
                table.code
                for table in tables
                if (profile := baseline.get(table.code)) is not None and profile.requires_review
            }
            if not candidate_codes:
                return assistance_result("validation_profile", available=self.available, candidates=0)
            if not self.available:
                return assistance_result(
                    "validation_profile",
                    available=False,
                    candidates=len(candidate_codes),
                    message=(
                        f"{self._settings.api_key_env}가 없어 불확실 프로파일을 검토 대상으로 유지했습니다."
                    ),
                )

            assisted = repository.ensure_profiles(
                report_id=report_id,
                tables=tables,
                provider=GPTProfileDraftProvider(review_only=True, model=self._settings.model),
                refresh_needs_review=True,
            )
            unresolved = sum(
                1
                for code in candidate_codes
                if (profile := assisted.get(code)) is None or profile.requires_review
            )
            return assistance_result(
                "validation_profile",
                available=True,
                candidates=len(candidate_codes),
                applied=len(candidate_codes) - unresolved,
                proposed=unresolved,
            )
        except Exception as error:
            # Profile assistance is an optional preflight.  Never turn a
            # successfully stored annual report into a failed upload because
            # this optional stage or one of its dependencies is unavailable.
            return assistance_result(
                "validation_profile",
                available=self.available,
                candidates=0,
                message=f"검수 프로파일 보조를 건너뛰고 업로드를 유지했습니다: {str(error)[:200]}",
            )

    @property
    def available(self) -> bool:
        return bool(
            self._decision_provider
            or (self._settings.enabled and self._settings.api_key)
        )

    def _sync_unresolved_import_reviews(
        self,
        report_id: int,
        candidates: list[dict[str, Any]],
    ) -> None:
        """Expose unresolved parser candidates as draft review targets.

        A parser warning on its own is stored as provenance.  Once the user
        explicitly asks for LLM assistance, an omitted, rejected, or merely
        proposed answer means that warning is still operationally unresolved
        and must be visible as ``확인 필요`` in the new report.
        """

        if not candidates:
            return
        table_ids = [int(candidate["table_id"]) for candidate in candidates]
        with connect(self._db_path) as connection:
            init_db(connection)
            decisions = {
                int(row["target_key"]): str(row["status"] or "")
                for row in connection.execute(
                    """
                    SELECT target_key, status
                    FROM report_llm_assistance_decisions
                    WHERE report_id = ? AND workflow_kind = 'full_import'
                    """,
                    (report_id,),
                ).fetchall()
                if str(row["target_key"] or "").isdigit()
            }
            with connection:
                for candidate in candidates:
                    table_id = int(candidate["table_id"])
                    if decisions.get(table_id) == "applied":
                        connection.execute(
                            """
                            DELETE FROM generated_report_table_status
                            WHERE report_id = ? AND table_id = ?
                              AND generation_status = 'parse_review'
                            """,
                            (report_id, table_id),
                        )
                        continue
                    warnings = candidate.get("warnings") or []
                    warning_text = "; ".join(str(value) for value in warnings[:3])
                    connection.execute(
                        """
                        INSERT INTO generated_report_table_status (
                            report_id, table_id, source_table_id,
                            generation_status, generation_message
                        ) VALUES (?, ?, NULL, 'parse_review', ?)
                        ON CONFLICT(report_id, table_id) DO UPDATE SET
                            generation_status = CASE
                                WHEN generated_report_table_status.generation_status = 'parse_review'
                                THEN excluded.generation_status
                                ELSE generated_report_table_status.generation_status
                            END,
                            generation_message = CASE
                                WHEN generated_report_table_status.generation_status = 'parse_review'
                                THEN excluded.generation_message
                                ELSE generated_report_table_status.generation_message
                            END
                        """,
                        (
                            report_id,
                            table_id,
                            (
                                "LLM 파싱 보조 후에도 헤더·단위·기준일 해석을 확정하지 못했습니다. "
                                f"원인: {warning_text or '파싱 구조 확인 필요'}"
                            ),
                        ),
                    )

    def _request(
        self,
        workflow_kind: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        if self._decision_provider is not None:
            return self._decision_provider(workflow_kind, payload)
        body = {
            "model": self._settings.model,
            "reasoning": {"effort": "low"},
            "input": [
                {
                    "role": "system",
                    "content": [{
                        "type": "input_text",
                        "text": (
                            "You analyze Korean government statistical tables. "
                            "Return a conservative plan only; never invent data."
                        ),
                    }],
                },
                {
                    "role": "user",
                    "content": [{
                        "type": "input_text",
                        "text": json.dumps(payload, ensure_ascii=False),
                    }],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": f"{workflow_kind}_assistance",
                    "strict": True,
                    "schema": schema,
                }
            },
            "max_output_tokens": 12000,
        }
        response = ResponsesTransport(self._settings).create(body)
        return parse_responses_json(response)

    def _apply_import_decisions(
        self,
        report_id: int,
        candidates: list[dict[str, Any]],
        response: dict[str, Any],
    ) -> dict[str, object]:
        known = {int(item["table_id"]): item for item in candidates}
        proposed = applied = rejected = 0
        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                for raw in response.get("decisions", []):
                    if not isinstance(raw, dict):
                        continue
                    table_id = integer(raw.get("table_id"), default=0)
                    candidate = known.get(table_id)
                    if candidate is None:
                        rejected += 1
                        continue
                    confidence = confidence_value(raw.get("confidence"))
                    action = str(raw.get("action") or "review")
                    changes: dict[str, Any] = {}
                    if action == "interpret" and confidence >= 0.95:
                        header_count = integer(raw.get("header_row_count"), default=0)
                        row_count = int(candidate["row_count"])
                        if 1 <= header_count < row_count:
                            connection.execute(
                                "UPDATE stat_table_cells SET is_header = CASE WHEN row_index < ? THEN 1 ELSE 0 END WHERE table_id = ?",
                                (header_count, table_id),
                            )
                            changes["header_row_count"] = header_count
                        for column, field in (("unit", "unit"), ("base_date", "base_date")):
                            suggestion = str(raw.get(field) or "").strip()
                            if suggestion and not str(candidate.get(field) or "").strip():
                                connection.execute(
                                    f"UPDATE stat_tables SET {column} = ? WHERE id = ? AND report_id = ?",
                                    (suggestion, table_id, report_id),
                                )
                                changes[field] = suggestion
                    status = "applied" if changes else "proposed"
                    proposed += status == "proposed"
                    applied += status == "applied"
                    plan = {**raw, "validated_changes": changes, "prompt_version": PROMPT_VERSION}
                    save_decision(
                        connection,
                        report_id=report_id,
                        workflow_kind="full_import",
                        target_key=str(table_id),
                        status=status,
                        confidence=confidence,
                        model=self._settings.model,
                        reason=str(raw.get("reason") or ""),
                        plan=plan,
                    )
        return assistance_result(
            "full_import", available=True, candidates=len(candidates),
            proposed=proposed, applied=applied, rejected=rejected,
        )

    def _apply_increment_decisions(
        self,
        report_id: int,
        candidates: list[dict[str, Any]],
        response: dict[str, Any],
    ) -> dict[str, object]:
        from app.services.incremental_yearbook_service import IncrementalYearbookService

        known_targets = {str(item["target_key"]): item for item in candidates}
        proposed = applied = rejected = 0
        incremental = IncrementalYearbookService(self._db_path)
        decisions: list[tuple[dict[str, Any], str, float, str]] = []
        for raw in response.get("decisions", []):
            if not isinstance(raw, dict):
                continue
            target_key = str(raw.get("target_key") or "")
            candidate = known_targets.get(target_key)
            if candidate is None:
                rejected += 1
                continue
            confidence = confidence_value(raw.get("confidence"))
            status = "proposed"
            if (
                raw.get("action") == "connect"
                and confidence >= 0.95
                and str(raw.get("table_code") or "") == str(candidate.get("table_code") or "")
                and str(raw.get("source_key") or "").startswith("M")
                and str(raw.get("source_key") or "") in candidate.get("allowed_source_keys", [])
            ):
                try:
                    preview = incremental.preview_mapping(
                        report_id=report_id,
                        table_code=str(raw["table_code"]),
                        source_key=str(raw["source_key"]),
                    )
                    if bool(preview.get("compatible")):
                        incremental.set_mapping(
                            report_id=report_id,
                            table_code=str(raw["table_code"]),
                            source_key=str(raw["source_key"]),
                        )
                        with connect(self._db_path) as connection:
                            init_db(connection)
                            with connection:
                                connection.execute(
                                    """
                                    UPDATE report_incremental_table_mappings
                                    SET match_method = 'llm_assisted',
                                        confirmed_by_user = 0,
                                        updated_at = CURRENT_TIMESTAMP
                                    WHERE report_id = ? AND table_code = ?
                                    """,
                                    (report_id, str(raw["table_code"])),
                                )
                        status = "applied"
                except Exception:
                    status = "proposed"
            applied += status == "applied"
            proposed += status == "proposed"
            decisions.append((raw, status, confidence, target_key))

        with connect(self._db_path) as connection:
            init_db(connection)
            with connection:
                for raw, status, confidence, target_key in decisions:
                    plan = {**raw, "prompt_version": PROMPT_VERSION}
                    save_decision(
                        connection,
                        report_id=report_id,
                        workflow_kind="increment",
                        target_key=target_key,
                        status=status,
                        confidence=confidence,
                        model=self._settings.model,
                        reason=str(raw.get("reason") or ""),
                        plan=plan,
                    )
                    table_code = str(raw.get("table_code") or "")
                    if table_code:
                        attach_increment_plan(connection, report_id, table_code, plan, status)
        return assistance_result(
            "increment", available=True, candidates=len(candidates),
            proposed=proposed, applied=applied, rejected=rejected,
        )


def import_candidates(connection: DatabaseConnection, report_id: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT table_row.id, table_row.code, table_row.title, table_row.unit,
               table_row.base_date, table_row.parse_warnings_json,
               COUNT(cell.id) AS cell_count,
               COUNT(DISTINCT cell.row_index) AS row_count,
               SUM(CASE WHEN cell.is_header = 1 THEN 1 ELSE 0 END) AS header_cells
        FROM stat_tables table_row
        LEFT JOIN stat_table_cells cell ON cell.table_id = table_row.id
        WHERE table_row.report_id = ?
        GROUP BY table_row.id
        ORDER BY table_row.table_order, table_row.id
        """,
        (report_id,),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        warnings = json_list(str(row["parse_warnings_json"] or "[]"))
        if not warnings and int(row["cell_count"] or 0) > 0 and int(row["header_cells"] or 0) > 0:
            continue
        matrix = table_matrix(connection, int(row["id"]), max_rows=40, max_columns=30)
        result.append({
            "table_id": int(row["id"]),
            "code": str(row["code"] or ""),
            "title": str(row["title"] or ""),
            "unit": str(row["unit"] or ""),
            "base_date": str(row["base_date"] or ""),
            "row_count": int(row["row_count"] or 0),
            "cell_count": int(row["cell_count"] or 0),
            "warnings": warnings[:20],
            "matrix": matrix,
        })
    return result[:80]


def increment_candidates(connection: DatabaseConnection, report_id: int) -> list[dict[str, Any]]:
    upload = connection.execute(
        "SELECT payload_json FROM report_incremental_uploads WHERE report_id = ?",
        (report_id,),
    ).fetchone()
    if upload is None:
        return []
    datasets = json_object(str(upload["payload_json"] or "{}"))
    rows = connection.execute(
        """
        SELECT mapping.table_code, mapping.source_key, mapping.match_method,
               mapping.reason_code, mapping.candidates_json, mapping.evidence_json,
               table_row.id AS table_id, table_row.title, status.generation_status
        FROM report_incremental_table_mappings mapping
        LEFT JOIN stat_tables table_row
          ON table_row.report_id = mapping.report_id AND table_row.code = mapping.table_code
        LEFT JOIN generated_report_table_status status
          ON status.report_id = mapping.report_id AND status.table_id = table_row.id
        WHERE mapping.report_id = ?
          AND (status.generation_status = 'mapping_review' OR mapping.match_method = 'new_increment')
        ORDER BY table_row.table_order, mapping.table_code
        """,
        (report_id,),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        source_key = str(row["source_key"] or "")
        dataset = datasets.get(source_key, {}) if isinstance(datasets.get(source_key), dict) else {}
        deterministic_candidates = json_list(str(row["candidates_json"] or "[]"))[:5]
        candidate_datasets: list[dict[str, Any]] = []
        for candidate in deterministic_candidates:
            if not isinstance(candidate, dict):
                continue
            candidate_key = str(candidate.get("source_key") or "")
            candidate_dataset = datasets.get(candidate_key)
            if not isinstance(candidate_dataset, dict):
                continue
            candidate_items = candidate_dataset.get("items", [])
            candidate_values = candidate_dataset.get("values", [])
            candidate_datasets.append({
                "source_key": candidate_key,
                "title": str(candidate_dataset.get("title") or ""),
                "department": str(candidate_dataset.get("department") or ""),
                "reference_time": str(candidate_dataset.get("reference_time") or ""),
                "score_evidence": candidate,
                "items": [
                    {
                        "data_no": item.get("data_no"),
                        "label": item.get("label"),
                        "full_name": item.get("full_name"),
                    }
                    for item in candidate_items[:50]
                    if isinstance(item, dict)
                ],
                "sample_values": candidate_values[:40],
            })
        items = dataset.get("items", []) if isinstance(dataset, dict) else []
        values = dataset.get("values", []) if isinstance(dataset, dict) else []
        if row["match_method"] == "new_increment" and (not items or not values):
            continue
        target_key = (
            f"increment:{source_key}"
            if str(row["match_method"] or "") == "new_increment"
            else f"table:{row['table_code']}"
        )
        result.append({
            "target_key": target_key,
            "table_code": str(row["table_code"] or "") if row["table_id"] is not None else "",
            "table_title": str(row["title"] or ""),
            "table_matrix": (
                table_matrix(connection, int(row["table_id"]), max_rows=30, max_columns=20)
                if row["table_id"] is not None else []
            ),
            "current_source_key": source_key,
            "reason_code": str(row["reason_code"] or ""),
            "deterministic_candidates": deterministic_candidates,
            "candidate_datasets": candidate_datasets,
            "allowed_source_keys": [
                str(item.get("source_key") or "")
                for item in candidate_datasets
                if item.get("source_key")
            ],
            "dataset": {
                "source_key": source_key,
                "title": str(dataset.get("title") or "") if isinstance(dataset, dict) else "",
                "department": str(dataset.get("department") or "") if isinstance(dataset, dict) else "",
                "reference_time": str(dataset.get("reference_time") or "") if isinstance(dataset, dict) else "",
                "items": [
                    {
                        "data_no": item.get("data_no"),
                        "label": item.get("label"),
                        "full_name": item.get("full_name"),
                    }
                    for item in items[:80] if isinstance(item, dict)
                ],
                "sample_values": values[:80],
            },
        })
    return result[:100]


def table_matrix(
    connection: DatabaseConnection,
    table_id: int,
    *,
    max_rows: int,
    max_columns: int,
) -> list[list[str]]:
    rows = connection.execute(
        """
        SELECT row_index, col_index, text_value
        FROM stat_table_cells
        WHERE table_id = ? AND row_index < ? AND col_index < ?
        ORDER BY row_index, col_index
        """,
        (table_id, max_rows, max_columns),
    ).fetchall()
    if not rows:
        return []
    row_count = max(int(row["row_index"]) for row in rows) + 1
    column_count = max(int(row["col_index"]) for row in rows) + 1
    matrix = [["" for _ in range(column_count)] for _ in range(row_count)]
    for row in rows:
        matrix[int(row["row_index"])][int(row["col_index"])] = str(row["text_value"] or "")
    return matrix


def save_decision(
    connection: DatabaseConnection,
    *,
    report_id: int,
    workflow_kind: str,
    target_key: str,
    status: str,
    confidence: float,
    model: str,
    reason: str,
    plan: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO report_llm_assistance_decisions (
            report_id, workflow_kind, target_key, status, confidence,
            model, reason, plan_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(report_id, workflow_kind, target_key) DO UPDATE SET
            status = excluded.status,
            confidence = excluded.confidence,
            model = excluded.model,
            reason = excluded.reason,
            plan_json = excluded.plan_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            report_id, workflow_kind, target_key, status, confidence,
            model, reason, json.dumps(plan, ensure_ascii=False),
        ),
    )


def attach_increment_plan(
    connection: DatabaseConnection,
    report_id: int,
    table_code: str,
    plan: dict[str, Any],
    status: str,
) -> None:
    row = connection.execute(
        "SELECT evidence_json FROM report_incremental_table_mappings WHERE report_id = ? AND table_code = ?",
        (report_id, table_code),
    ).fetchone()
    if row is None:
        return
    evidence = json_object(str(row["evidence_json"] or "{}"))
    evidence["llm_assistance"] = {"status": status, **plan}
    connection.execute(
        "UPDATE report_incremental_table_mappings SET evidence_json = ?, updated_at = CURRENT_TIMESTAMP WHERE report_id = ? AND table_code = ?",
        (json.dumps(evidence, ensure_ascii=False), report_id, table_code),
    )


def assistance_result(
    workflow_kind: str,
    *,
    available: bool,
    candidates: int,
    proposed: int = 0,
    applied: int = 0,
    rejected: int = 0,
    message: str = "",
) -> dict[str, object]:
    return {
        "workflow_kind": workflow_kind,
        "available": available,
        "candidates": candidates,
        "proposed": proposed,
        "applied": applied,
        "rejected": rejected,
        "message": message,
    }


def confidence_value(value: object) -> float:
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.0


def integer(value: object, *, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def json_list(value: str) -> list[Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
