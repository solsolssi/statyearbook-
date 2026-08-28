#!/usr/bin/env python3
"""Build a layout-preserving HWPX demo yearbook from a selected Markdown list.

The Markdown demo is the source of truth for which logical statistics to keep.
Each selected statistic is copied as the original HWPX top-level paragraph
range (title, metadata table, data tables, notes and source line), so merged
cells and the authored table layout remain untouched.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile
import xml.etree.ElementTree as ET

from app.ingest.hwpx_importer import (
    element_text,
    is_title_table,
    parse_title_block,
    superscript_char_ids,
    table_matrix_with_footnotes,
)


SECTION_NAME_RE = re.compile(r"Contents/section(\d+)\.xml$")
DEMO_CODE_RE = re.compile(r"^((?:\d+-)+\d+)\s+", re.MULTILINE)
OPF_NAMESPACE = "http://www.idpf.org/2007/opf/"


def selected_codes(markdown_path: Path) -> list[str]:
    codes = list(dict.fromkeys(DEMO_CODE_RE.findall(markdown_path.read_text(encoding="utf-8"))))
    if not codes:
        raise ValueError(f"시연용 MD에서 통계 번호를 찾지 못했습니다: {markdown_path}")
    return codes


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def title_indexes(root: ET.Element, superscript_ids: set[str]) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for index, child in enumerate(root):
        for table in child.iter():
            if local_name(table.tag) != "tbl":
                continue
            matrix, _ = table_matrix_with_footnotes(table, superscript_ids)
            text = element_text(table)
            title = parse_title_block(text)
            if title and is_title_table(matrix, text):
                found.append((index, title[0]))
                break
    return found


def selected_section(root: ET.Element, codes: set[str], superscript_ids: set[str]) -> tuple[ET.Element, set[str]]:
    indexes = title_indexes(root, superscript_ids)
    starts = [(index, code) for index, code in indexes if code in codes]
    if not starts:
        return root, set()

    children = list(root)
    first_title_index = indexes[0][0] if indexes else len(children)
    # Preserve each original section's setup and chapter heading.  This includes
    # the section properties required for a valid rendered HWPX document.
    keep_indexes = set(range(first_title_index))
    matched_codes: set[str] = set()
    for position, (start, code) in enumerate(indexes):
        if code not in codes:
            continue
        end = indexes[position + 1][0] if position + 1 < len(indexes) else len(children)
        keep_indexes.update(range(start, end))
        matched_codes.add(code)

    root[:] = [deepcopy(child) for index, child in enumerate(children) if index in keep_indexes]
    return root, matched_codes


def rewrite_content_hpf(payload: bytes, retained_section_numbers: set[int]) -> bytes:
    root = ET.fromstring(payload)
    manifest = root.find(f"{{{OPF_NAMESPACE}}}manifest")
    spine = root.find(f"{{{OPF_NAMESPACE}}}spine")
    if manifest is None or spine is None:
        raise ValueError("Contents/content.hpf의 manifest 또는 spine을 찾지 못했습니다.")

    retained_ids = {f"section{number}" for number in retained_section_numbers}
    for item in list(manifest):
        item_id = item.attrib.get("id", "")
        if item_id.startswith("section") and item_id not in retained_ids:
            manifest.remove(item)
    for itemref in list(spine):
        item_id = itemref.attrib.get("idref", "")
        if item_id.startswith("section") and item_id not in retained_ids:
            spine.remove(itemref)

    metadata = root.find(f"{{{OPF_NAMESPACE}}}metadata")
    if metadata is not None:
        title = metadata.find(f"{{{OPF_NAMESPACE}}}title")
        if title is not None:
            title.text = "2026 행정안전통계연보 시연용"
    ET.register_namespace("opf", OPF_NAMESPACE)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build_demo_hwpx(source_path: Path, markdown_path: Path, output_path: Path) -> list[str]:
    codes = selected_codes(markdown_path)
    target_codes = set(codes)
    transformed_sections: dict[str, bytes] = {}
    retained_section_numbers: set[int] = set()
    matched_codes: set[str] = set()

    with ZipFile(source_path) as source:
        superscript_ids = superscript_char_ids(source.read("Contents/header.xml"))
        for name in source.namelist():
            match = SECTION_NAME_RE.fullmatch(name)
            if match is None or match.group(1) == "0":
                continue
            root = ET.fromstring(source.read(name))
            selected_root, matched = selected_section(root, target_codes, superscript_ids)
            if not matched:
                continue
            transformed_sections[name] = ET.tostring(
                selected_root,
                encoding="utf-8",
                xml_declaration=True,
            )
            retained_section_numbers.add(int(match.group(1)))
            matched_codes.update(matched)

        missing = [code for code in codes if code not in matched_codes]
        if missing:
            raise ValueError(f"원본 HWPX에서 찾지 못한 시연 통계 번호: {', '.join(missing)}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as output:
            for info in source.infolist():
                section_match = SECTION_NAME_RE.fullmatch(info.filename)
                if section_match is not None:
                    section_number = int(section_match.group(1))
                    if section_number not in retained_section_numbers:
                        continue
                    output.writestr(info, transformed_sections[info.filename])
                    continue
                if info.filename == "Contents/content.hpf":
                    output.writestr(
                        info,
                        rewrite_content_hpf(source.read(info.filename), retained_section_numbers),
                    )
                    continue
                output.writestr(info, source.read(info.filename))

    return codes


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a selected-statistics demo HWPX.")
    parser.add_argument("--source", type=Path, required=True, help="원본 전체 HWPX")
    parser.add_argument("--demo-md", type=Path, required=True, help="시연용 통계 목록 MD")
    parser.add_argument("--output", type=Path, required=True, help="생성할 HWPX 경로")
    args = parser.parse_args()

    codes = build_demo_hwpx(args.source, args.demo_md, args.output)
    print(f"생성 완료: {args.output} ({len(codes)}개 통계)")
    print("통계 번호: " + ", ".join(codes))


if __name__ == "__main__":
    main()
