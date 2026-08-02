from __future__ import annotations

import argparse
from pathlib import Path

from app.db.connection import DatabaseConnection, connect_sqlite
from app.db.schema import init_db


ESSENTIAL_TABLES = (
    "annual_reports",
    "stat_tables",
    "stat_table_cells",
    "series_import_batches",
    "statistical_datasets",
    "statistical_dataset_versions",
    "statistical_observations",
    "statistical_dataset_items",
    "statistical_values",
    "statistical_value_revisions",
    "statistical_period_metadata",
    "yearbook_table_recipes",
    "yearbook_table_update_policies",
    "yearbook_edition_manifest",
    "validation_profiles",
    "translation_glossary",
    "translation_glossary_aliases",
)


def prepare_test_database(*, source: Path, destination: Path) -> dict[str, int]:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"보존할 기존 DB를 찾을 수 없습니다: {source}")
    if destination.exists():
        raise FileExistsError(
            f"테스트 DB가 이미 존재합니다: {destination}. "
            "기존 테스트 결과를 보호하기 위해 덮어쓰지 않았습니다."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with connect_sqlite(destination) as connection:
        init_db(connection)
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("ATTACH DATABASE ? AS legacy", (str(source),))
        try:
            active_ids = [
                int(row["id"])
                for row in connection.execute(
                    """
                    SELECT id FROM legacy.annual_reports
                    WHERE COALESCE(is_archived, 0) = 0
                    ORDER BY id
                    """
                ).fetchall()
            ]
            with connection:
                for table in ESSENTIAL_TABLES:
                    copy_table(connection, table)
                connection.execute("UPDATE annual_reports SET is_archived = 1, is_template = 0")
                if active_ids:
                    connection.execute(
                        f"""
                        UPDATE annual_reports
                        SET is_template = 1
                        WHERE id IN ({','.join('?' for _ in active_ids)})
                        """,
                        active_ids,
                    )
        finally:
            connection.execute("DETACH DATABASE legacy")
        connection.execute("PRAGMA foreign_keys = ON")
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"테스트 DB 외래키 검사에 실패했습니다: {len(violations)}건")
        counts = {
            "templates": scalar(connection, "SELECT COUNT(*) FROM annual_reports WHERE is_template = 1"),
            "reports": scalar(connection, "SELECT COUNT(*) FROM annual_reports"),
            "tables": scalar(connection, "SELECT COUNT(*) FROM stat_tables"),
            "datasets": scalar(connection, "SELECT COUNT(*) FROM statistical_datasets"),
            "values": scalar(connection, "SELECT COUNT(*) FROM statistical_values"),
        }
        connection.execute("VACUUM")
    return counts


def copy_table(connection: DatabaseConnection, table: str) -> None:
    if not table_exists(connection, "legacy", table):
        return
    destination_columns = {
        str(row["name"])
        for row in connection.execute(f"PRAGMA main.table_info({table})").fetchall()
    }
    source_columns = [
        str(row["name"])
        for row in connection.execute(f"PRAGMA legacy.table_info({table})").fetchall()
    ]
    columns = [column for column in source_columns if column in destination_columns]
    if not columns:
        return
    joined = ", ".join(f'"{column}"' for column in columns)
    connection.execute(
        f'INSERT INTO main."{table}" ({joined}) SELECT {joined} FROM legacy."{table}"'
    )


def table_exists(connection: DatabaseConnection, schema: str, table: str) -> bool:
    return (
        connection.execute(
            f"SELECT 1 FROM {schema}.sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def scalar(connection: DatabaseConnection, sql: str) -> int:
    row = connection.execute(sql).fetchone()
    return int(row[0] or 0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="기존 연보/원장 DB를 보존한 채 숨김 템플릿 기반 테스트 DB를 만듭니다."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    counts = prepare_test_database(source=args.source, destination=args.destination)
    print(f"테스트 DB 생성 완료: {args.destination.resolve()}")
    for key, value in counts.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
