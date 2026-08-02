from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.db.connection import DB_PATH
from app.yearbook_data.relational_import import RelationalSourceDataImporter


def main() -> None:
    parser = argparse.ArgumentParser(
        description="전체 원장과 연도별 증분 Excel을 별도 통계 원장 DB에 적재합니다."
    )
    parser.add_argument("--full-info", type=Path, required=True)
    parser.add_argument("--full-items", type=Path, required=True)
    parser.add_argument("--full-values", type=Path, required=True)
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--delta-info", type=Path)
    parser.add_argument("--delta-items", type=Path)
    parser.add_argument("--delta-values", type=Path)
    parser.add_argument("--target-year", type=int)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()

    delta_paths = (args.delta_info, args.delta_items, args.delta_values)
    if any(delta_paths) and not all(delta_paths):
        parser.error("증분 적재는 --delta-info, --delta-items, --delta-values가 모두 필요합니다.")
    if all(delta_paths) and args.target_year is None:
        parser.error("증분 적재에는 --target-year가 필요합니다.")

    importer = RelationalSourceDataImporter(args.db)
    full = importer.import_full(
        info_path=args.full_info,
        item_path=args.full_items,
        value_path=args.full_values,
        schema_path=args.schema,
    )
    payload: dict[str, object] = {"full": full.__dict__}
    if all(delta_paths):
        delta = importer.import_delta(
            info_path=args.delta_info,
            item_path=args.delta_items,
            value_path=args.delta_values,
            target_year=args.target_year,
        )
        payload["incremental"] = delta.__dict__
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
