from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.db.connection import DatabaseConnection
from app.domain.enums import ValidationStatus
from app.domain.validation import ValidationResult
from app.validation.models import ValidationIssueRecord


CHECK_INSERT_SQL = """
    INSERT INTO validation_checks (
        run_id, table_id, profile_id, rule_id, check_type, check_label,
        location, row_index, col_index, current_value, expected_value,
        difference, status, severity, detail, formula, confidence
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def save_validation_results(
    connection: DatabaseConnection,
    *,
    run_id: int,
    results: Iterable[ValidationResult],
) -> int:
    rows = [_result_row(run_id, result) for result in results]
    if rows:
        connection.executemany(CHECK_INSERT_SQL, rows)
    return len(rows)


def save_validation_result(
    connection: DatabaseConnection,
    *,
    run_id: int,
    result: ValidationResult,
) -> None:
    connection.execute(CHECK_INSERT_SQL, _result_row(run_id, result))


def upsert_validation_result(
    connection: DatabaseConnection,
    *,
    run_id: int,
    result: ValidationResult,
) -> bool:
    """Insert or fully replace one materialized result.

    The natural identity intentionally excludes the generated id and outcome
    fields. Language and blue-source reviews can therefore be rerun without
    creating duplicate checks.

    Returns ``True`` when a new row was inserted.
    """

    existing = find_validation_result_id(
        connection,
        run_id=run_id,
        table_id=result.table_id,
        rule_id=result.rule_id,
        location=result.location,
        current_value=result.current_value,
    )
    if existing is None:
        save_validation_result(connection, run_id=run_id, result=result)
        return True

    update_validation_result(connection, result_id=existing, result=result)
    return False


def find_validation_result_id(
    connection: DatabaseConnection,
    *,
    run_id: int,
    table_id: int,
    rule_id: str,
    location: str,
    current_value: str,
) -> int | None:
    row = connection.execute(
        """
        SELECT id
        FROM validation_checks
        WHERE run_id = ? AND table_id = ? AND rule_id = ?
          AND location = ? AND current_value = ?
        ORDER BY id
        LIMIT 1
        """,
        (run_id, table_id, rule_id, location, current_value),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def update_validation_result(
    connection: DatabaseConnection,
    *,
    result_id: int,
    result: ValidationResult,
) -> None:
    connection.execute(
        """
        UPDATE validation_checks
        SET table_id = ?, profile_id = ?, rule_id = ?, check_type = ?,
            check_label = ?, location = ?, row_index = ?, col_index = ?,
            current_value = ?, expected_value = ?, difference = ?, status = ?,
            severity = ?, detail = ?, formula = ?, confidence = ?
        WHERE id = ?
        """,
        (*_result_row_without_run(result), result_id),
    )


def update_validation_result_outcome(
    connection: DatabaseConnection,
    *,
    expected_value: str | None,
    difference: str | None,
    status: ValidationStatus | str,
    severity: str,
    detail: str,
    result_id: int | None = None,
    run_id: int | None = None,
    table_id: int | None = None,
    rule_id: str | None = None,
    location: str | None = None,
    current_value: str | None = None,
) -> int:
    """Update only the review outcome, either by id or candidate identity."""

    params: list[object] = [
        expected_value,
        difference,
        str(status),
        severity,
        detail,
    ]
    if result_id is not None:
        where = "id = ?"
        params.append(result_id)
    else:
        required = (run_id, table_id, rule_id, location, current_value)
        if any(value is None for value in required):
            raise ValueError("result_id 또는 완전한 검수 결과 식별자가 필요합니다.")
        where = (
            "run_id = ? AND table_id = ? AND rule_id = ? "
            "AND location = ? AND current_value = ?"
        )
        params.extend(required)

    cursor = connection.execute(
        f"""
        UPDATE validation_checks
        SET expected_value = ?, difference = ?, status = ?, severity = ?, detail = ?
        WHERE {where}
        """,
        params,
    )
    return max(int(cursor.rowcount or 0), 0)


def merge_legacy_issues(
    checks: Sequence[ValidationResult],
    issues: Sequence[ValidationIssueRecord],
) -> list[ValidationResult]:
    """Keep old rule-engine callers compatible without dual DB storage."""

    merged = list(checks)
    identities = {_result_identity(result) for result in merged}
    for issue in issues:
        result = ValidationResult(
            table_id=issue.table_id,
            rule_id=issue.rule_id,
            check_type=issue.issue_type,
            check_label=issue.issue_type,
            location=issue.location,
            row_index=issue.row_index,
            col_index=issue.col_index,
            current_value=issue.current_value,
            expected_value=issue.expected_value,
            difference=issue.difference,
            status=issue.status,
            severity=issue.severity,
            detail=issue.detail,
            formula=issue.formula,
        )
        identity = _result_identity(result)
        if identity not in identities:
            merged.append(result)
            identities.add(identity)
    return merged


def delete_validation_results(
    connection: DatabaseConnection,
    *,
    run_id: int,
    rule_ids: Sequence[str] = (),
    check_types: Sequence[str] = (),
) -> int:
    filters = ["run_id = ?"]
    params: list[object] = [run_id]
    if rule_ids:
        filters.append(f"rule_id IN ({', '.join('?' for _ in rule_ids)})")
        params.extend(rule_ids)
    if check_types:
        filters.append(f"check_type IN ({', '.join('?' for _ in check_types)})")
        params.extend(check_types)
    cursor = connection.execute(
        f"DELETE FROM validation_checks WHERE {' AND '.join(filters)}",
        params,
    )
    return max(int(cursor.rowcount or 0), 0)


def delete_validation_results_by_expected_value(
    connection: DatabaseConnection,
    *,
    run_id: int,
    rule_ids: Sequence[str],
    expected_value: str,
) -> int:
    if not rule_ids:
        return 0
    filters = ["run_id = ?", f"rule_id IN ({', '.join('?' for _ in rule_ids)})", "expected_value = ?"]
    cursor = connection.execute(
        f"DELETE FROM validation_checks WHERE {' AND '.join(filters)}",
        (run_id, *rule_ids, expected_value),
    )
    return max(int(cursor.rowcount or 0), 0)


def delete_validation_result(
    connection: DatabaseConnection,
    *,
    run_id: int,
    table_id: int,
    rule_id: str,
    location: str,
    current_value: str,
) -> int:
    cursor = connection.execute(
        """
        DELETE FROM validation_checks
        WHERE run_id = ? AND table_id = ? AND rule_id = ?
          AND location = ? AND current_value = ?
        """,
        (run_id, table_id, rule_id, location, current_value),
    )
    return max(int(cursor.rowcount or 0), 0)


def delete_validation_result_ids(
    connection: DatabaseConnection,
    result_ids: Sequence[int],
) -> int:
    if not result_ids:
        return 0
    cursor = connection.executemany(
        "DELETE FROM validation_checks WHERE id = ?",
        [(result_id,) for result_id in result_ids],
    )
    rowcount = int(cursor.rowcount or 0)
    return max(rowcount, 0) if rowcount >= 0 else len(result_ids)


def delete_validation_results_for_candidate_kind(
    connection: DatabaseConnection,
    *,
    run_id: int,
    candidate_kind_pattern: str,
    rule_ids: Sequence[str],
) -> int:
    """Delete materialized checks linked to one language-candidate source."""

    if not rule_ids:
        return 0
    placeholders = ", ".join("?" for _ in rule_ids)
    rows = connection.execute(
        f"""
        SELECT DISTINCT check_result.id
        FROM validation_checks check_result
        JOIN linguistic_review_candidates candidate
          ON candidate.run_id = check_result.run_id
         AND candidate.table_id = check_result.table_id
         AND candidate.location = check_result.location
         AND candidate.current_value = check_result.current_value
        WHERE check_result.run_id = ?
          AND check_result.rule_id IN ({placeholders})
          AND candidate.candidate_kind LIKE ?
        """,
        (run_id, *rule_ids, candidate_kind_pattern),
    ).fetchall()
    return delete_validation_result_ids(
        connection,
        [int(row["id"]) for row in rows],
    )


def validation_problem_count(
    connection: DatabaseConnection,
    *,
    run_id: int,
) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*) AS issue_count
        FROM validation_checks
        WHERE run_id = ? AND status <> ?
        """,
        (run_id, ValidationStatus.NORMAL.value),
    ).fetchone()
    return int(row["issue_count"] if row else 0)


def refresh_run_issue_count(
    connection: DatabaseConnection,
    *,
    run_id: int,
) -> int:
    issue_count = validation_problem_count(connection, run_id=run_id)
    connection.execute(
        "UPDATE validation_runs SET issue_count = ? WHERE id = ?",
        (issue_count, run_id),
    )
    return issue_count


def _result_row(run_id: int, result: ValidationResult) -> tuple[object, ...]:
    return (
        run_id,
        *_result_row_without_run(result),
    )


def _result_row_without_run(result: ValidationResult) -> tuple[object, ...]:
    return (
        result.table_id,
        result.profile_id,
        result.rule_id,
        result.check_type,
        result.check_label,
        result.location,
        result.row_index,
        result.col_index,
        result.current_value,
        result.expected_value,
        result.difference,
        str(result.status),
        str(result.severity),
        result.detail,
        result.formula,
        result.confidence,
    )


def _result_identity(result: ValidationResult) -> tuple[object, ...]:
    return (
        result.table_id,
        result.rule_id,
        result.location,
        result.row_index,
        result.col_index,
        result.current_value,
        result.expected_value,
        str(result.status),
    )
