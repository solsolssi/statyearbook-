from __future__ import annotations

import re


DASH_VALUES = {"-", "－", "―"}
NUMBER_LIKE_RE = re.compile(r"^[-+]?(?:0,)?\d{1,3}(?:,\d{3})*(?:\.\d+)?$")


def repair_region_split_rows(matrix: list[list[str]], footnote_matrix: list[list[str]]) -> None:
    repair_shifted_small_business_amount_column(matrix, footnote_matrix)
    repair_local_government_sejong_eup_myeon_dong_column(matrix, footnote_matrix)
    trim_trailing_empty_columns(matrix, footnote_matrix)

    if not looks_like_upper_lower_region_split_table(matrix):
        return

    for row_index, row in enumerate(matrix):
        if len(row) < 8 or not is_special_upper_region_label(row[0]):
            continue
        if not (
            is_number_like(row[2])
            and is_number_like(row[3])
            and is_dash(row[4])
            and is_dash(row[5])
            and is_dash(row[6])
            and is_dash(row[7])
        ):
            continue

        row[4] = row[2]
        row[5] = row[3]
        if row_index < len(footnote_matrix) and len(footnote_matrix[row_index]) >= 8:
            footnote_matrix[row_index][4] = footnote_matrix[row_index][2]
            footnote_matrix[row_index][5] = footnote_matrix[row_index][3]


def trim_trailing_empty_columns(
    matrix: list[list[str]],
    footnote_matrix: list[list[str]],
) -> None:
    """Remove physical grid columns left empty after a structural repair.

    HWPX preserves grid cells that are visually absorbed by a merged cell.
    Once a value is moved to its visual column, retaining an all-empty final
    column leaks a phantom field into validation and later yearbook updates.
    """

    width = max(
        max((len(row) for row in matrix), default=0),
        max((len(row) for row in footnote_matrix), default=0),
    )
    while width and not any(
        (width - 1 < len(row) and row[width - 1].strip())
        for row in [*matrix, *footnote_matrix]
    ):
        width -= 1

    for row in matrix:
        del row[width:]
    for row in footnote_matrix:
        del row[width:]


def detach_spanning_small_business_note(
    table_code: str,
    matrix: list[list[str]],
    footnote_matrix: list[list[str]],
) -> str:
    """Move the 2015~2017 merged small-business guide out of data cells.

    The two flood-insurance tables use one cell spanning three year rows to
    explain that the small-business programme starts in 2018.  A rectangular
    matrix necessarily repeats that text for each covered row, but it is a
    note, not three observations.  Keep the authored text as table metadata
    and leave the unavailable values empty.
    """

    base_code = table_code.split(" 표", 1)[0].strip()
    if base_code != "7-3-9-4":
        return ""

    note_values: list[str] = []
    for row in matrix:
        for value in row:
            normalized = normalize_text(value)
            if "시범사업" not in normalized or "nationwideenforcement" not in normalized:
                continue
            if value not in note_values:
                note_values.append(value)

    if len(note_values) != 1:
        return ""

    note_value = note_values[0]
    for row_index, row in enumerate(matrix):
        for col_index, value in enumerate(row):
            if value != note_value:
                continue
            row[col_index] = ""
            if row_index < len(footnote_matrix) and col_index < len(footnote_matrix[row_index]):
                footnote_matrix[row_index][col_index] = ""

    return f"#주) 소상공인: {note_value}"


def normalize_flood_insurance_small_business_guide(
    table_code: str,
    matrix: list[list[str]],
) -> None:
    """Restore Korean/English boundaries in 7-3-9-2's merged guide cell.

    The original HWPX intentionally displays the 2015--2017 guide inside the
    merged ``소상공인/건수`` cell.  Its Korean paragraph ends immediately before
    the leading English count (``시군구22 cities``), so a plain text extractor
    incorrectly assigns 22/37 to Korean.  Keep the cell in the table and
    rebuild its authored Korean and English lines without changing data.
    """

    if table_code.split(" 표", 1)[0].strip() != "7-3-9-2":
        return

    for row in matrix:
        for column_index, value in enumerate(row):
            normalized = normalize_text(value)
            if "시범사업" not in normalized or "nationwideenforcement" not in normalized:
                continue
            row[column_index] = normalize_small_business_guide_text(value)


def normalize_small_business_guide_text(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    korean_lines: list[str] = []
    english_lines: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.search(r"[가-힣]", line):
            next_line = lines[index + 1] if index + 1 < len(lines) else ""
            trailing_count = re.match(r"^(.*[가-힣])(\d+)$", line)
            if trailing_count and re.search(r"[A-Za-z]", next_line) and not re.search(r"[가-힣]", next_line):
                korean_lines.append(trailing_count.group(1))
                english_lines.append(f"{trailing_count.group(2)} {next_line}")
                index += 2
                continue
            korean_lines.append(line)
        elif re.search(r"[A-Za-z]", line):
            english_lines.append(line)
        else:
            korean_lines.append(line)
        index += 1

    return "\n".join([*korean_lines, *english_lines])


def repair_shifted_small_business_amount_column(
    matrix: list[list[str]],
    footnote_matrix: list[list[str]],
) -> None:
    """Move small-business amount values out of a trailing blank grid column.

    Some HWPX tables keep the visual ``소상공인/금액`` cell at column 8 while
    body values are stored in the next physical grid column.  Leaving that
    shape as-is creates one empty amount column and one unlabeled numeric
    column.  The repair is deliberately pattern-based so unrelated sparse
    financial tables are not shifted.
    """

    if len(matrix) < 3 or max((len(row) for row in matrix), default=0) < 10:
        return
    header_text = normalize_text(" ".join(" ".join(row) for row in matrix[:2]))
    if not (
        "소상공인" in header_text
        and "smallbusiness" in header_text
        and "금액" in header_text
    ):
        return

    source_col = 9
    target_col = 8
    shifted_rows = 0
    for row_index, row in enumerate(matrix[2:], start=2):
        if len(row) <= source_col or len(row) <= target_col:
            continue
        if row[target_col].strip() or not is_number_like(row[source_col]):
            continue
        row[target_col] = row[source_col]
        row[source_col] = ""
        shifted_rows += 1
        if row_index < len(footnote_matrix) and len(footnote_matrix[row_index]) > source_col:
            footnote_matrix[row_index][target_col] = footnote_matrix[row_index][source_col]
            footnote_matrix[row_index][source_col] = ""

    return


def repair_local_government_sejong_eup_myeon_dong_column(
    matrix: list[list[str]],
    footnote_matrix: list[list[str]],
) -> None:
    """Move Sejong's eup/myeon/dong count out of the district column.

    In the local-government-organization table, Sejong has no county/district
    value but has 24 eup/myeon/dong units.  Some HWPX grid exports place the
    value under the previous physical column because the visual header spans
    are uneven.  Keeping it there breaks the grand-total calculation.
    """

    if len(matrix) < 2 or max((len(row) for row in matrix), default=0) < 5:
        return
    header_text = normalize_text(" ".join(" ".join(row) for row in matrix[:2]))
    if not ("군" in header_text and "구" in header_text and "읍" in header_text and "면" in header_text and "동" in header_text):
        return
    header_rows = matrix[: min(2, len(matrix))]
    county_col = find_header_column(header_rows, "군")
    district_col = find_header_column(header_rows, "구")
    eup_col = find_header_column(header_rows, "읍")
    if county_col is None or district_col is None or eup_col is None:
        return
    for row_index, row in enumerate(matrix[1:], start=1):
        if len(row) <= max(county_col, district_col, eup_col):
            continue
        if "세종" not in normalize_text(row[0]):
            continue
        if row[eup_col].strip() not in {"", "-"} or not is_number_like(row[district_col]):
            continue
        if row[county_col].strip() not in {"", "-"}:
            continue
        row[eup_col] = row[district_col]
        row[district_col] = "-"
        if row_index < len(footnote_matrix) and len(footnote_matrix[row_index]) > max(district_col, eup_col):
            footnote_matrix[row_index][eup_col] = footnote_matrix[row_index][district_col]
            footnote_matrix[row_index][district_col] = ""


def find_header_column(header_rows: list[list[str]], needle: str) -> int | None:
    for row in header_rows:
        for col_index, value in enumerate(row):
            normalized = normalize_text(value)
            if "구분" in normalized or "classification" in normalized:
                continue
            if needle in normalized:
                return col_index
    return None


def looks_like_upper_lower_region_split_table(matrix: list[list[str]]) -> bool:
    header_text = normalize_text(" ".join(" ".join(row) for row in matrix[:2]))
    return (
        "총계" in header_text
        and "조례" in header_text
        and "규칙" in header_text
        and ("시도" in header_text or "metropolitancityprovince" in header_text)
        and ("시군자치구" in header_text or "citycountydistrict" in header_text)
    )


def is_special_upper_region_label(value: str) -> bool:
    normalized = normalize_text(value)
    return "세종" in normalized or "sejong" in normalized or "제주" in normalized or "jeju" in normalized


def is_dash(value: str) -> bool:
    return value.strip() in DASH_VALUES


def is_number_like(value: str) -> bool:
    return NUMBER_LIKE_RE.fullmatch(value.strip()) is not None


def normalize_text(value: str) -> str:
    return re.sub(r"[\s･·.,/&]+", "", value).lower()
