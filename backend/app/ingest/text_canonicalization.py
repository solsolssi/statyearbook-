from __future__ import annotations

import re

from app.validation.models import restore_hyphenated_line_breaks


ENGLISH_TITLE_CHARS = r"A-Za-z0-9 ,:&/().%\[\]·･+=\-'’‘′ʼ~"
ENGLISH_TITLE_RE = re.compile(
    rf"(?<![A-Za-z0-9])([A-Za-z][{ENGLISH_TITLE_CHARS}]{{2,}}|\d+-[A-Za-z][{ENGLISH_TITLE_CHARS}]{{2,}})$"
)
ENGLISH_ONLY_RE = re.compile(rf"(?=[{ENGLISH_TITLE_CHARS}]*[A-Za-z])[{ENGLISH_TITLE_CHARS}]+")

# These are line-wrap hyphens found in the source typography, not lexical
# hyphens.  Keep the list deliberately narrow so terms such as ``Non-powered``
# and ``Government-Level`` are not damaged.
BROKEN_WORD_REPLACEMENTS = {
    "Classifi-cation": "Classification",
    "Equip-ment": "Equipment",
    "Organi-zation": "Organization",
    "GovernmentLevel": "Government-Level",
    "Nonpowered": "Non-powered",
    "Subtotal": "Sub-total",
    "SmallScale": "Small-Scale",
    "FloodProne": "Flood-Prone",
    "Donghaesi": "Donghae-si",
    "Suseonggu": "Suseong-gu",
    "Gyeyanggu": "Gyeyang-gu",
    "Yuseonggu": "Yuseong-gu",
    "Yongsangu": "Yongsan-gu",
}


def split_bilingual(text: str) -> tuple[str, str]:
    cleaned = re.sub(r"\s+", " ", text).replace("\\~", "~").replace("᭼", "･").strip(" :;?")
    if not cleaned:
        return "", ""

    if ENGLISH_ONLY_RE.fullmatch(cleaned):
        return "", cleaned

    match = ENGLISH_TITLE_RE.search(cleaned)
    if match and match.start() > 0:
        prefix = cleaned[: match.start()]
        if prefix.endswith("(") and re.fullmatch(
            r"(?:[A-Za-z]/[A-Za-z]|[A-Za-z](?:[+\-][A-Za-z])+|[A-Za-z]=[A-Za-z](?:[+\-][A-Za-z])+)\)",
            match.group(1),
        ):
            return cleaned, ""
        return cleaned[: match.start()].strip(), match.group(1).strip()

    return cleaned, ""


def separate_bilingual_lines(text: str) -> str:
    separated: list[str] = []
    for line in text.splitlines():
        korean, english = split_bilingual(line)
        if korean and english:
            separated.extend((korean, english))
        elif korean or english:
            separated.append(korean or english)
    return "\n".join(separated)


def canonicalize_cell_text(value: str) -> str:
    """Normalize format-specific wrapping without deleting visible content."""

    cleaned = (
        value.replace("\\*", "*")
        .replace("\\_", "_")
        .replace("\\~", "~")
        .replace("\xa0", " ")
    )
    cleaned = restore_hyphenated_line_breaks(cleaned)
    for current, expected in BROKEN_WORD_REPLACEMENTS.items():
        cleaned = cleaned.replace(current, expected)

    # Manual page wrapping is format-dependent.  Preserve semantic bullet
    # boundaries and the Korean/English boundary, while allowing the browser
    # to wrap long prose according to the actual column width.
    collapsed = re.sub(r"\s+", " ", cleaned).strip()
    if not collapsed:
        return ""
    segments = [
        segment.strip()
        for segment in re.split(r"(?=\s(?:[*▪※])\s*)", collapsed)
        if segment.strip()
    ]
    return "\n".join(separate_bilingual_lines(segment) for segment in segments)


def cell_text_comparison_key(value: str) -> str:
    """Return a comparison key that ignores physical typesetting spacing.

    The stored and displayed text is not changed.  This only prevents HWPX
    letter spacing and Markdown word wrapping from being reported as a data
    update between report snapshots.
    """

    return re.sub(r"\s+", "", canonicalize_cell_text(value))


def canonicalize_note_text(value: str) -> str:
    """Remove pagination-only wrapping while retaining each logical note.

    Markdown exports wrap long notes at page/text boundaries, while HWPX can
    concatenate the same boundary.  Neither representation is meaningful to
    users, so notes are normalized by their ``#주``/source boundaries rather
    than by physical lines.
    """

    cleaned = (
        value.replace("\\*", "*")
        .replace("\\_", "_")
        .replace("\\~", "~")
        .replace("\xa0", " ")
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Repairs for boundaries that the HWPX text run extractor joins without
    # whitespace.  These are full domain terms, not broad character rules, so
    # legitimate compounds and numeric values remain untouched.
    for current, expected in {
        "기준순세계잉여금": "기준 순세계잉여금",
        "자유무역협정추진기획단": "자유무역협정 추진기획단",
        ")시군통제장비": ") 시군통제장비",
        "경남5서해안 다목적": "경남5 서해안 다목적",
    }.items():
        cleaned = cleaned.replace(current, expected)

    # A spaced hyphen between Korean clauses is a wrapped bullet in the HWPX
    # export; Markdown represents the same boundary as a newline.
    cleaned = re.sub(r"(?<=[가-힣])[-–]\s+(?=[가-힣])", " ", cleaned)
    cleaned = re.sub(r"(?<!\d)(\d+)\.(?=[가-힣A-Za-z])", r"\1. ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Restore only semantic boundaries.  Soft line wrapping stays removed.
    cleaned = re.sub(r"\s+(?=(?:#\s*주|\[출처\s*:))", "\n", cleaned)
    return cleaned
