from __future__ import annotations

import argparse

from app.operations.retention import SourceRetentionService


def main() -> None:
    parser = argparse.ArgumentParser(description="Run annual-report maintenance tasks.")
    parser.add_argument(
        "--prune-sources",
        action="store_true",
        help="Find original uploads past their configured retention period.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete expired sources. Without this flag the command is a dry run.",
    )
    args = parser.parse_args()
    if not args.prune_sources:
        parser.error("실행할 유지보수 작업을 지정하세요: --prune-sources")

    result = SourceRetentionService().prune(dry_run=not args.apply)
    print(
        "source retention: "
        f"candidates={result.candidates}, deleted={result.deleted}, "
        f"failed={result.failed}, dry_run={result.dry_run}"
    )
    for error in result.errors:
        print(error)
    if result.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
