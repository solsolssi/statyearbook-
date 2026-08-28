#!/usr/bin/env python3
"""Build the 20-table 2026 demonstration yearbook from the uploaded source MD.

The output intentionally preserves each selected table block verbatim so it can
exercise the same parser and validation paths as the full yearbook.
"""

from __future__ import annotations

from pathlib import Path
import re


SOURCE = Path(
    "backend/uploads/4f2327451a75406da57aab7288a6de4d_"
    "2026통계연보초안.md"
)
OUTPUT = Path("generated/2026_시연용_통계연보_20표.md")

# Representative validation cases are retained below. The two 7-3 tables are
# known-good ratio-validation cases from the latest 2026 run.
SELECTED_CODES = (
    "1-1-2",
    "1-1-4",
    "1-2-3-3",
    "2-1-1-7",
    "2-1-5-2",
    "2-2-2-1",
    "2-2-5-1",
    "2-2-11-2",
    "2-2-11-3",
    "2-2-12-1",
    "4-1-1-3",
    "4-1-1-4",
    "4-1-2-1",
    "4-1-5-2",
    "4-1-6-1",
    "4-1-7-2",
    "4-1-7-3",
    "6-2-11-2",   # total validation issue: 641,435 vs 641,453
    "7-3-10-1",   # normal ratio validation
    "8-1-1-1",     # required archive table
)

HEADING = re.compile(r"^(?:[0-9]+(?:-[0-9]+)+|부록\s*[0-9]+)\s+")


def is_heading_for(line: str, code: str) -> bool:
    return line.startswith(f"{code} ")


def selected_blocks(source: str) -> list[tuple[str, str]]:
    lines = source.splitlines(keepends=True)
    starts: dict[str, int] = {}
    for index, line in enumerate(lines):
        for code in SELECTED_CODES:
            if code not in starts and is_heading_for(line, code):
                starts[code] = index

    missing = [code for code in SELECTED_CODES if code not in starts]
    if missing:
        raise RuntimeError(f"Source headings not found: {', '.join(missing)}")

    blocks: list[tuple[str, str]] = []
    for code in SELECTED_CODES:
        start = starts[code]
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if HEADING.match(lines[index]):
                end = index
                break
        blocks.append((code, "".join(lines[start:end]).strip()))
    return blocks


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    blocks = selected_blocks(source)
    header = """# 2026 행정안전통계연보 시연용\n\n이 문서는 2026 전체 연보 MD에서 20개 통계를 원문 그대로 추출한 시연 자료입니다.\n\n- 필수 포함 표: 6-2-11-2, 8-1-1-1\n- 정상 비율 검수 표: 7-3-10-1\n- LLM 언어 검수 후보가 많은 표 5개는 시연 시간을 줄이기 위해 제외했습니다.\n\n"""
    content = header + "\n\n".join(block for _, block in blocks) + "\n"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"Wrote {OUTPUT} ({len(blocks)} table blocks)")


if __name__ == "__main__":
    main()
