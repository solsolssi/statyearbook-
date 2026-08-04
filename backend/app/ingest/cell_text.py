from __future__ import annotations

from collections.abc import Iterable
import re


YEAR_FOOTNOTE_CAPTURE_RE = re.compile(r"^(\d{4})\s*(\d+\))$")
LEADING_ZERO_THOUSANDS_RE = re.compile(r"^([+-]?)0,(\d{3})(\.\d+)?$")
FOOTNOTE_DEFINITION_RE = re.compile(r"(?:^|\s)#?\s*주\s*(\d+)\)")
INLINE_FOOTNOTE_RE = re.compile(r"(?<=[가-힣A-Za-z)])(\d+\))(?=\s*(?:$|\(|[A-Z]))")


def normalize_cell_text(value: str) -> str:
    text, _ = split_cell_text(value)
    return text


def footnote_markers_from_texts(values: Iterable[str]) -> set[str]:
    return {
        f"{match.group(1)})"
        for value in values
        for match in FOOTNOTE_DEFINITION_RE.finditer(value)
    }


def split_cell_text(
    value: str,
    footnote_markers: Iterable[str] = (),
) -> tuple[str, str]:
    cleaned = value.strip()
    markers = sorted(set(footnote_markers), key=len, reverse=True)
    lines = cleaned.splitlines()
    found_markers: list[str] = []
    for line_index, line in enumerate(lines):
        stripped_line = line.rstrip()
        for marker in markers:
            if not marker:
                continue
            marker_match = re.search(
                rf"{re.escape(marker)}(?=\s*(?:$|\(|[A-Z]))",
                stripped_line,
            )
            if marker_match is None:
                continue
            prefix = stripped_line[: marker_match.start()]
            if prefix.count("(") > prefix.count(")"):
                # The suffix closes a numeric/text parenthesis such as
                # ``47.3(42.4)``; it is data, not a footnote marker.
                continue
            body_text = (
                prefix
                + stripped_line[marker_match.end() :]
            ).strip()
            if not body_text:
                continue
            lines[line_index] = body_text
            if marker not in found_markers:
                found_markers.append(marker)
            break
    if found_markers:
        return normalize_numeric_display_text("\n".join(lines).strip()), " ".join(found_markers)

    year_footnote = YEAR_FOOTNOTE_CAPTURE_RE.fullmatch(cleaned)
    if year_footnote:
        return year_footnote.group(1), year_footnote.group(2)
    return normalize_numeric_display_text(cleaned), ""


def inline_footnote_markers(value: str) -> set[str]:
    """Find footnote-like markers in header text when rich style is absent."""

    return {match.group(1) for match in INLINE_FOOTNOTE_RE.finditer(value)}


def normalize_numeric_display_text(value: str) -> str:
    match = LEADING_ZERO_THOUSANDS_RE.fullmatch(value)
    if not match:
        return value
    sign, digits, decimal_part = match.groups()
    normalized_digits = str(int(digits))
    return f"{sign}{normalized_digits}{decimal_part or ''}"
