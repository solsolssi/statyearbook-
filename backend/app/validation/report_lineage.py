from __future__ import annotations

from app.db.connection import DatabaseConnection


def report_lineage_ids(
    connection: DatabaseConnection,
    report_id: int,
    *,
    include_self: bool = True,
) -> list[int]:
    """Return a report and its explicitly selected base-report ancestry.

    A report year is deliberately not part of this lookup. Two independently
    uploaded reports from the same year are separate validation histories until
    the user explicitly creates a revision from one of them.
    """

    lineage: list[int] = []
    current_id: int | None = report_id
    visited: set[int] = set()
    while current_id is not None and current_id not in visited:
        visited.add(current_id)
        row = connection.execute(
            "SELECT id, base_report_id FROM annual_reports WHERE id = ?",
            (current_id,),
        ).fetchone()
        if row is None:
            break
        lineage.append(int(row["id"]))
        current_id = (
            int(row["base_report_id"])
            if row["base_report_id"] is not None
            else None
        )
    return lineage if include_self else lineage[1:]

