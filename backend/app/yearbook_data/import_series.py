from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.db.connection import DB_PATH
from app.yearbook_data.repository import SeriesImportRepository


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Excel 시계열 원장을 수정 이력이 남는 canonical DB에 적재합니다."
    )
    parser.add_argument("source", type=Path, help=".xlsx 또는 .xls 시계열 파일")
    parser.add_argument(
        "--kind",
        choices=("full", "incremental"),
        required=True,
        help="전체 원장 또는 증분 입력 구분",
    )
    parser.add_argument(
        "--target-year",
        type=int,
        help="증분이 반영될 연보 연도(예: 2027)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help=f"SQLite DB 경로(기본값: {DB_PATH})",
    )
    args = parser.parse_args()
    if args.kind == "incremental" and args.target_year is None:
        parser.error("--kind incremental에는 --target-year가 필요합니다.")

    result = SeriesImportRepository(args.db).import_workbook(
        args.source,
        import_kind=args.kind,
        target_year=args.target_year,
    )
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
