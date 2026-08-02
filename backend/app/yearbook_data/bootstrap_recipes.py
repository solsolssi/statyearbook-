from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.db.connection import DB_PATH
from app.services.yearbook_reproduction_service import YearbookReproductionService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="기존 연보를 기준으로 원장 연결 및 표시 기간 초안 레시피를 생성합니다."
    )
    parser.add_argument("--report-id", type=int, required=True)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = YearbookReproductionService(args.db).bootstrap_draft_recipes(
        report_id=args.report_id
    )
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
