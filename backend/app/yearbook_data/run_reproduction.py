from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.db.connection import DB_PATH
from app.services.yearbook_reproduction_build_service import (
    YearbookReproductionBuildService,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="원장으로 staging 셀을 만들고 기존 연보와 비교합니다. 검수는 실행하지 않습니다."
    )
    parser.add_argument("--report-id", type=int, required=True)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()
    result = YearbookReproductionBuildService(args.db).run(report_id=args.report_id)
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
