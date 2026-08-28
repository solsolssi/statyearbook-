"""Build an editable public-sector presentation for the yearbook validator.

Slides 2 and 3 are intentionally retained from the supplied draft, with only
minor spacing/terminology corrections. Slides 4 onward are rebuilt as editable
PowerPoint shapes, text boxes, and tables.
"""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
from typing import Iterable, Sequence

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE, MSO_SHAPE_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt


FONT = "Arial"

NAVY = "0C2F61"
NAVY_2 = "153E70"
BLUE = "1F5A91"
BLUE_2 = "2F78B7"
SKY = "DDEDF7"
SKY_2 = "EEF6FB"
CYAN = "48A9C7"
TEAL = "2F7D68"
TEAL_BG = "E8F5F1"
AMBER = "B97818"
AMBER_BG = "FFF4DE"
RED = "C94655"
RED_BG = "FDECEF"
# Keep the main palette intentionally compact. Purple aliases the primary blue
# so non-status elements remain visually consistent across the deck.
PURPLE = BLUE
PURPLE_BG = SKY_2
TEXT = "172331"
MUTED = "667085"
MUTED_2 = "8A96A3"
BORDER = "D9E0E6"
LIGHT = "F7F9FB"
WHITE = "FFFFFF"


def C(value: str) -> RGBColor:
    return RGBColor.from_string(value)


def set_run_style(
    run,
    *,
    size: float,
    color: str = TEXT,
    bold: bool = False,
    italic: bool = False,
    font_name: str = FONT,
) -> None:
    run.font.name = font_name
    run.font.size = Pt(size)
    run.font.color.rgb = C(color)
    run.font.bold = bold
    run.font.italic = italic
    r_pr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        typeface = r_pr.find(qn(tag))
        if typeface is None:
            typeface = OxmlElement(tag)
            r_pr.append(typeface)
        typeface.set("typeface", font_name)


def force_font_family(prs: Presentation, font_name: str = FONT) -> None:
    """Apply one font to slide text, tables, masters, layouts, notes and theme fallbacks."""
    for part in prs.part.package.iter_parts():
        element = getattr(part, "_element", None)
        if element is not None:
            for node in element.iter():
                if "typeface" in node.attrib:
                    node.set("typeface", font_name)
            continue

        # python-pptx keeps theme files as raw package parts. Rewrite their
        # font-scheme fallbacks as well so newly added text also resolves to Arial.
        if str(part.partname).startswith("/ppt/theme/"):
            theme = etree.fromstring(part.blob)
            for node in theme.iter():
                if "typeface" in node.attrib:
                    node.set("typeface", font_name)
            part._blob = etree.tostring(theme, encoding="UTF-8", xml_declaration=True, standalone=True)


def add_text(
    slide,
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    size: float = 11,
    color: str = TEXT,
    bold: bool = False,
    italic: bool = False,
    align: PP_ALIGN = PP_ALIGN.LEFT,
    valign: MSO_ANCHOR = MSO_ANCHOR.TOP,
    margin: float = 0.02,
    name: str | None = None,
) -> object:
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    style = shape._element.find(qn("p:style"))
    if style is not None:
        shape._element.remove(style)
    if name:
        shape.name = name
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = Inches(margin)
    tf.margin_right = Inches(margin)
    tf.margin_top = Inches(margin)
    tf.margin_bottom = Inches(margin)
    tf.vertical_anchor = valign
    p = tf.paragraphs[0]
    p.alignment = align
    p.space_before = Pt(0)
    p.space_after = Pt(0)
    run = p.add_run()
    run.text = text
    set_run_style(run, size=size, color=color, bold=bold, italic=italic)
    return shape


def add_rich_text(
    slide,
    runs: Sequence[dict],
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    align: PP_ALIGN = PP_ALIGN.LEFT,
    valign: MSO_ANCHOR = MSO_ANCHOR.TOP,
    margin: float = 0.02,
    name: str | None = None,
) -> object:
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    style = shape._element.find(qn("p:style"))
    if style is not None:
        shape._element.remove(style)
    if name:
        shape.name = name
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = Inches(margin)
    tf.margin_right = Inches(margin)
    tf.margin_top = Inches(margin)
    tf.margin_bottom = Inches(margin)
    tf.vertical_anchor = valign
    p = tf.paragraphs[0]
    p.alignment = align
    p.space_before = Pt(0)
    p.space_after = Pt(0)
    for spec in runs:
        run = p.add_run()
        run.text = spec["text"]
        set_run_style(
            run,
            size=spec.get("size", 11),
            color=spec.get("color", TEXT),
            bold=spec.get("bold", False),
            italic=spec.get("italic", False),
        )
    return shape


def add_bullets(
    slide,
    items: Iterable[str],
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    size: float = 10,
    color: str = TEXT,
    bullet_color: str | None = None,
    gap: float = 3,
    margin: float = 0.02,
    name: str | None = None,
) -> object:
    shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    style = shape._element.find(qn("p:style"))
    if style is not None:
        shape._element.remove(style)
    if name:
        shape.name = name
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = Inches(margin)
    tf.margin_right = Inches(margin)
    tf.margin_top = Inches(margin)
    tf.margin_bottom = Inches(margin)
    tf.vertical_anchor = MSO_ANCHOR.TOP
    for index, item in enumerate(items):
        p = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.space_before = Pt(0)
        p.space_after = Pt(gap)
        p.line_spacing = 1.08
        bullet = p.add_run()
        bullet.text = "• "
        set_run_style(bullet, size=size, color=bullet_color or BLUE_2, bold=True)
        body = p.add_run()
        body.text = item
        set_run_style(body, size=size, color=color)
    return shape


def add_shape(
    slide,
    shape_type,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str = WHITE,
    line: str | None = BORDER,
    line_width: float = 0.8,
    radius_name: str | None = None,
) -> object:
    shape = slide.shapes.add_shape(
        shape_type,
        Inches(x),
        Inches(y),
        Inches(w),
        Inches(h),
    )
    # The Google Slides theme in the source deck maps the default shape effect
    # style to a very large white shadow. Remove that inherited style so newly
    # added editable shapes render consistently in PowerPoint and Quick Look.
    style = shape._element.find(qn("p:style"))
    if style is not None:
        shape._element.remove(style)
    if radius_name:
        shape.name = radius_name
    shape.fill.solid()
    shape.fill.fore_color.rgb = C(fill)
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = C(line)
        shape.line.width = Pt(line_width)
    return shape


def add_rect(
    slide,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str = WHITE,
    line: str | None = BORDER,
    line_width: float = 0.8,
    name: str | None = None,
) -> object:
    return add_shape(
        slide,
        MSO_AUTO_SHAPE_TYPE.RECTANGLE,
        x,
        y,
        w,
        h,
        fill=fill,
        line=line,
        line_width=line_width,
        radius_name=name,
    )


def add_round_rect(
    slide,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str = WHITE,
    line: str | None = BORDER,
    line_width: float = 0.8,
    name: str | None = None,
) -> object:
    # Use a standard rectangle rather than DrawingML ``roundRect``. The source
    # deck's Google theme is rendered by macOS Quick Look with oversized corner
    # masks for newly-added roundRect objects, which can obscure adjacent text.
    # A clean rectangular card remains fully editable and renders consistently.
    return add_shape(
        slide,
        MSO_AUTO_SHAPE_TYPE.RECTANGLE,
        x,
        y,
        w,
        h,
        fill=fill,
        line=line,
        line_width=line_width,
        radius_name=name,
    )


def add_circle(
    slide,
    x: float,
    y: float,
    d: float,
    *,
    fill: str,
    line: str | None = None,
    name: str | None = None,
) -> object:
    # Use a Unicode circle glyph instead of a DrawingML ellipse. Quick Look can
    # duplicate ellipse mask artifacts from the Google-exported theme, whereas
    # the glyph remains an editable text object and renders consistently.
    return add_text(
        slide,
        "●",
        x,
        y,
        d,
        d,
        size=max(10.0, d * 58),
        color=fill,
        bold=True,
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
        margin=0,
        name=name or "원형 배지",
    )


def add_arrow(slide, x: float, y: float, w: float, h: float, *, color: str = CYAN) -> object:
    display_w = max(w, 0.16)
    display_h = max(h, 0.16)
    return add_shape(
        slide,
        MSO_AUTO_SHAPE_TYPE.RIGHT_ARROW,
        x - (display_w - w) / 2,
        y - (display_h - h) / 2,
        display_w,
        display_h,
        fill=color,
        line=None,
        radius_name="흐름 화살표",
    )


def add_down_arrow(slide, x: float, y: float, w: float, h: float, *, color: str = CYAN) -> object:
    display_w = max(w, 0.18)
    display_h = max(h, 0.18)
    return add_shape(
        slide,
        MSO_AUTO_SHAPE_TYPE.DOWN_ARROW,
        x - (display_w - w) / 2,
        y - (display_h - h) / 2,
        display_w,
        display_h,
        fill=color,
        line=None,
        radius_name="아래 흐름 화살표",
    )


def add_pill(
    slide,
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str,
    color: str,
    size: float = 9,
    bold: bool = True,
    line: str | None = None,
    name: str | None = None,
) -> object:
    add_round_rect(slide, x, y, w, h, fill=fill, line=line, name=name or f"라벨_{text}")
    return add_text(
        slide,
        text,
        x,
        y,
        w,
        h,
        size=size,
        color=color,
        bold=bold,
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
        margin=0.02,
        name=f"라벨 텍스트_{text}",
    )


def add_number_badge(slide, number: int, x: float, y: float, *, fill: str = NAVY, d: float = 0.40) -> None:
    add_circle(slide, x, y, d, fill=fill, name=f"단계 {number} 배지")
    add_text(
        slide,
        str(number),
        x,
        y,
        d,
        d,
        size=10.8,
        color=WHITE,
        bold=True,
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
        margin=0,
        name=f"단계 {number}",
    )


def add_image_placeholder(
    slide,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    title: str,
    subtitle: str,
    name: str,
) -> object:
    frame = add_round_rect(slide, x, y, w, h, fill=LIGHT, line="B7C9D9", line_width=1.2, name=name)
    add_text(
        slide,
        "+",
        x + w / 2 - 0.28,
        y + h / 2 - 0.52,
        0.56,
        0.52,
        size=25,
        color=BLUE,
        bold=True,
        align=PP_ALIGN.CENTER,
        valign=MSO_ANCHOR.MIDDLE,
        margin=0,
        name=f"{name}_아이콘",
    )
    add_text(
        slide,
        title,
        x + 0.24,
        y + h / 2 + 0.02,
        w - 0.48,
        0.28,
        size=10.5,
        color=NAVY,
        bold=True,
        align=PP_ALIGN.CENTER,
        name=f"{name}_제목",
    )
    add_text(
        slide,
        subtitle,
        x + 0.24,
        y + h / 2 + 0.38,
        w - 0.48,
        0.24,
        size=8.0,
        color=MUTED,
        align=PP_ALIGN.CENTER,
        name=f"{name}_안내",
    )
    return frame


def clear_slide(slide) -> None:
    for shape in list(slide.shapes):
        element = shape._element
        element.getparent().remove(element)


def find_logo_blob(prs: Presentation) -> bytes:
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE and shape.image.ext.lower() == "png":
                # The white-cover logo is slightly smaller; use the normal dark-text mark.
                if len(shape.image.blob) > 5000:
                    return shape.image.blob
    raise RuntimeError("행정안전부 로고 이미지를 찾지 못했습니다.")


def add_header(
    slide,
    section: str,
    title: str,
    page: int,
    logo_blob: bytes,
    *,
    headline: str | None = None,
) -> None:
    main_title = headline or title
    add_text(
        slide,
        section,
        0.50,
        0.24,
        6.0,
        0.30,
        size=10.0,
        color=BLUE_2,
        bold=True,
        name="상단 분류",
    )
    add_text(
        slide,
        main_title,
        0.50,
        0.54,
        8.2,
        0.70,
        size=28.0,
        color=TEXT,
        bold=True,
        valign=MSO_ANCHOR.MIDDLE,
        name="슬라이드 제목",
    )
    slide.shapes.add_picture(BytesIO(logo_blob), Inches(8.42), Inches(0.08), width=Inches(1.50))
    add_rect(slide, 0.50, 1.34, 9.0, 0.015, fill=BORDER, line=None, name="제목 구분선")
    if headline:
        add_text(
            slide,
            title,
            0.50,
            1.44,
            8.90,
            0.32,
            size=12.0,
            color=MUTED,
            valign=MSO_ANCHOR.MIDDLE,
            name="슬라이드 부제목",
        )
    add_text(
        slide,
        "청년인턴 중간보고  |  행정안전부 데이터정보화담당관",
        0.50,
        5.31,
        4.8,
        0.18,
        size=7.0,
        color=MUTED_2,
        name="하단 문구",
    )
    add_text(
        slide,
        str(page),
        9.18,
        5.27,
        0.33,
        0.22,
        size=8.2,
        color=MUTED,
        bold=True,
        align=PP_ALIGN.RIGHT,
        name="페이지 번호",
    )


def reflow_body_for_tall_header(slide) -> None:
    """Compress vertical whitespace so existing editable content fits below the taller header."""
    header_names = {
        "상단 분류",
        "슬라이드 제목",
        "제목 구분선",
        "슬라이드 부제목",
        "하단 문구",
        "페이지 번호",
    }
    old_top = Inches(1.30)
    new_top = Inches(1.90)
    vertical_scale = 0.84

    for shape in slide.shapes:
        if shape.name in header_names:
            continue
        # The logo sits in the header and the footer sits below the content area.
        if shape.top < Inches(1.25) or shape.top >= Inches(5.20):
            continue

        original_top = shape.top
        original_height = shape.height
        shape.top = int(new_top + (original_top - old_top) * vertical_scale)

        if shape.has_table:
            for row in shape.table.rows:
                row.height = int(row.height * 0.86)
            shape.height = int(original_height * 0.86)
            continue

        has_visible_text = bool(shape.has_text_frame and shape.text.strip())
        if not has_visible_text and original_height > Inches(0.10):
            shape.height = int(original_height * vertical_scale)


def add_card_title(slide, title: str, x: float, y: float, w: float, *, color: str = NAVY, size: float = 12) -> None:
    add_text(
        slide,
        title,
        x,
        y,
        w,
        0.27,
        size=size,
        color=color,
        bold=True,
        valign=MSO_ANCHOR.MIDDLE,
        name=f"카드 제목_{title}",
    )


def set_notes(slide, text: str) -> None:
    notes_frame = slide.notes_slide.notes_text_frame
    if notes_frame is not None:
        notes_frame.text = text


def replace_text(slide, old: str, new: str) -> None:
    def replace_in_text_frame(text_frame) -> None:
        for paragraph in text_frame.paragraphs:
            for run in paragraph.runs:
                if old in run.text:
                    run.text = run.text.replace(old, new)

    for shape in slide.shapes:
        if shape.has_text_frame:
            replace_in_text_frame(shape.text_frame)
        if shape.has_table:
            for row in shape.table.rows:
                for cell in row.cells:
                    replace_in_text_frame(cell.text_frame)


def replace_page_number(slide, number: int, *, color: str = MUTED) -> None:
    """Replace Google-exported page-number fields with stable editable text."""
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        raw = shape.text.strip()
        if "#" not in raw and not (shape.left > Inches(9.0) and shape.top > Inches(5.0)):
            continue
        tf = shape.text_frame
        tf.clear()
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.RIGHT
        run = p.add_run()
        run.text = str(number)
        set_run_style(run, size=7.2, color=color)
        return


def set_table_cell(
    cell,
    text: str,
    *,
    size: float,
    color: str = TEXT,
    bold: bool = False,
    fill: str = WHITE,
    align: PP_ALIGN = PP_ALIGN.LEFT,
) -> None:
    cell.fill.solid()
    cell.fill.fore_color.rgb = C(fill)
    cell.margin_left = Inches(0.06)
    cell.margin_right = Inches(0.06)
    cell.margin_top = Inches(0.025)
    cell.margin_bottom = Inches(0.025)
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf = cell.text_frame
    tf.clear()
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    set_run_style(run, size=size, color=color, bold=bold)


def style_cover(slide) -> None:
    for shape in slide.shapes:
        if not shape.has_text_frame or "SECTION" not in shape.text:
            continue
        tf = shape.text_frame
        tf.clear()
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        run = p.add_run()
        run.text = "업무 개선 및 주요 기능"
        set_run_style(run, size=8.4, color=BLUE_2, bold=True)
    add_text(
        slide,
        "연보 업로드부터 검수·수정·재검수·다운로드까지",
        0.70,
        3.55,
        6.4,
        0.32,
        size=12,
        color="B7CCE6",
        name="표지 부제",
    )
    add_text(
        slide,
        "청년인턴 중간보고  |  행정안전부 데이터정보화담당관  |  2026. 8.",
        0.70,
        4.86,
        6.9,
        0.22,
        size=7.4,
        color="B7CCE6",
        name="표지 보고정보",
    )
    set_notes(
        slide,
        "통계연보 검수 보조 시스템의 배경, 구현 구조, 사용자 흐름과 향후 개선 방향을 설명합니다. "
        "이 시스템은 반복 검증을 자동화하되 최종 판단과 승인은 담당자가 수행하는 검수 보조 도구입니다.",
    )
    replace_page_number(slide, 1, color="B7CCE6")


def slide_comparison(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "프로젝트 소개", "통계연보 검수 보조 시스템", 3, logo_blob, headline="검수 체계 전환")

    panels = [
        (0.55, "기존 검수 방식", NAVY),
        (5.25, "통계연보 검수 보조 시스템", BLUE),
    ]
    for x, title, accent in panels:
        add_round_rect(slide, x, 1.34, 4.20, 3.28, fill=WHITE, line=BORDER, name=title)
        add_rect(slide, x, 1.34, 4.20, 0.52, fill=accent, line=None)
        add_text(slide, title, x + 0.20, 1.48, 3.80, 0.24, size=12, color=WHITE, bold=True, align=PP_ALIGN.CENTER)

    left_items = [
        "수백 개의 표를 반복 확인",
        "계산 오류·오탈자 누락 위험",
        "매년 유사한 표를 다시 검토",
        "검수 기준과 내역 공유 어려움",
    ]
    right_items = [
        "표별 규칙을 생성해 일괄 검수",
        "규칙 엔진과 선택적 LLM 보조",
        "동일 구조는 검수 프로파일 재사용",
        "통합 화면과 검수 리포트로 공유",
    ]
    for index, (left, right) in enumerate(zip(left_items, right_items), start=1):
        y = 2.02 + (index - 1) * 0.60
        add_round_rect(slide, 0.82, y, 3.66, 0.46, fill=LIGHT, line=None)
        add_number_badge(slide, index, 0.92, y + 0.04, fill=NAVY, d=0.36)
        add_text(slide, left, 1.42, y + 0.10, 2.82, 0.22, size=10.0, color=TEXT, bold=(index == 2), valign=MSO_ANCHOR.MIDDLE)
        add_round_rect(slide, 5.52, y, 3.66, 0.46, fill=SKY_2, line=None)
        add_text(slide, "✓", 5.68, y + 0.07, 0.32, 0.28, size=13, color=BLUE, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE, margin=0)
        add_text(slide, right, 6.10, y + 0.10, 2.84, 0.22, size=10.0, color=NAVY, bold=(index == 2), valign=MSO_ANCHOR.MIDDLE)

    add_arrow(slide, 4.78, 2.82, 0.34, 0.40, color=BLUE)
    add_round_rect(slide, 1.18, 4.82, 7.64, 0.28, fill=NAVY, line=None)
    add_text(slide, "반복 대조 업무를 구조화된 검수·수정·재검수 흐름으로 전환", 1.44, 4.87, 7.12, 0.18, size=9.0, color=WHITE, bold=True, align=PP_ALIGN.CENTER)

    set_notes(
        slide,
        "기존 검수의 반복성과 누락 위험을 표별 프로파일, 규칙 엔진, 검수 이력 재사용으로 개선합니다. "
        "자동화는 오류 후보와 판정 근거를 제시하고, 담당자는 최종 판단과 수정에 집중합니다.",
    )


def slide_problem_examples(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "문제 상황 예시", "놓치기 쉬운 오류와 반복되는 연도별 검수", 4, logo_blob, headline="반복 검수의 문제")

    add_round_rect(slide, 0.55, 1.34, 4.22, 3.66, fill=WHITE, line=BORDER, name="오류 사례 영역")
    add_rect(slide, 0.55, 1.34, 4.22, 0.50, fill=NAVY, line=None)
    add_text(slide, "계산 오류·오탈자 누락 사례", 0.78, 1.47, 3.76, 0.24, size=11.5, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    add_image_placeholder(
        slide,
        0.80,
        2.02,
        3.72,
        2.10,
        title="오류 사례 이미지 삽입",
        subtitle="합계 불일치·오탈자가 보이는 표 화면 권장",
        name="이미지 삽입_오류 사례",
    )
    add_round_rect(slide, 0.80, 4.30, 3.72, 0.43, fill=RED_BG, line=None)
    add_text(slide, "계산 불일치  ·  오탈자  ·  번역 표현", 1.02, 4.42, 3.28, 0.18, size=9.0, color=RED, bold=True, align=PP_ALIGN.CENTER)

    add_round_rect(slide, 5.03, 1.34, 4.42, 3.66, fill=WHITE, line=BORDER, name="연도별 비교 영역")
    add_rect(slide, 5.03, 1.34, 4.42, 0.50, fill=BLUE, line=None)
    add_text(slide, "표 구조는 같고, 셀 내용만 변경", 5.26, 1.47, 3.96, 0.24, size=11.5, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    add_image_placeholder(
        slide,
        5.28,
        2.02,
        1.80,
        1.94,
        title="전년도 표",
        subtitle="이미지 삽입",
        name="이미지 삽입_전년도 표",
    )
    add_image_placeholder(
        slide,
        7.40,
        2.02,
        1.80,
        1.94,
        title="금년도 표",
        subtitle="이미지 삽입",
        name="이미지 삽입_금년도 표",
    )
    add_arrow(slide, 7.11, 2.82, 0.24, 0.32, color=BLUE)
    add_round_rect(slide, 5.28, 4.16, 3.92, 0.57, fill=SKY_2, line=None)
    add_text(slide, "구조·항목 동일", 5.51, 4.25, 1.26, 0.20, size=9.1, color=BLUE, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, "→", 6.82, 4.24, 0.42, 0.22, size=14, color=BLUE, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, "셀 값만 변경", 7.30, 4.25, 1.54, 0.20, size=9.1, color=NAVY, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, "동일 프로파일을 재사용하고 현재 값만 다시 계산", 5.60, 4.52, 3.28, 0.17, size=7.8, color=MUTED, align=PP_ALIGN.CENTER)

    set_notes(
        slide,
        "왼쪽에는 계산 오류와 오탈자가 함께 보이는 실제 표 화면을 넣습니다. 오른쪽에는 전년도와 금년도 표를 나란히 배치해 구조와 항목은 동일하지만 셀 값만 바뀌는 점을 보여줍니다. "
        "동일 구조에서는 검수 프로파일을 재사용하고 현재 값만 다시 계산할 수 있다는 필요성을 연결해 설명합니다.",
    )


def slide_system_overview(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "시스템 소개", "업무 현황과 검수 근거를 한 화면에서 확인", 5, logo_blob, headline="통계연보 검수 플랫폼")

    add_image_placeholder(
        slide,
        0.55,
        1.34,
        6.28,
        3.66,
        title="메인 화면 스크린샷 삽입",
        subtitle="통계 연보 작업공간 전체 화면 · 16:9 비율 권장",
        name="이미지 삽입_시스템 메인 화면",
    )

    add_round_rect(slide, 7.08, 1.34, 2.37, 3.66, fill=WHITE, line=BORDER, name="제품 핵심 기능")
    add_rect(slide, 7.08, 1.34, 2.37, 0.56, fill=NAVY, line=None)
    add_text(slide, "통계연보 검수 보조", 7.25, 1.49, 2.03, 0.24, size=11.2, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    features = [
        (1, "연보·통계표 탐색", "연보 선택과 표 검색·상태 필터"),
        (2, "검수 현황 요약", "정상·확인 필요·오류 의심 집계"),
        (3, "근거 중심 확인", "문제 셀과 계산 근거 셀 연결"),
    ]
    for idx, title, body in features:
        y = 2.12 + (idx - 1) * 0.82
        add_number_badge(slide, idx, 7.32, y, fill=BLUE if idx < 3 else TEAL, d=0.38)
        add_text(slide, title, 7.84, y + 0.01, 1.34, 0.22, size=9.6, color=NAVY, bold=True)
        add_text(slide, body, 7.84, y + 0.28, 1.34, 0.34, size=7.9, color=MUTED, valign=MSO_ANCHOR.MIDDLE)
    add_round_rect(slide, 7.30, 4.64, 1.93, 0.24, fill=TEAL_BG, line=None)
    add_text(slide, "상세 확인 → 수정 → 재검수", 7.42, 4.68, 1.69, 0.16, size=7.8, color=TEAL, bold=True, align=PP_ALIGN.CENTER)

    set_notes(
        slide,
        "이 페이지의 큰 회색 영역에는 시스템 메인 작업 화면을 넣습니다. 연보와 통계표를 탐색하고, 검수 상태를 요약하며, 문제 셀과 근거 셀을 연결해 확인하는 제품 경험을 중심으로 소개합니다. "
        "실제 화면을 삽입한 뒤 자리표시자 안내 문구는 삭제하거나 이미지 뒤로 보내면 됩니다.",
    )


def slide_user_flow(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "사용 흐름", "업로드부터 다운로드까지, 하나의 검수 흐름", 6, logo_blob, headline="업무 처리 흐름")

    steps = [
        ("업로드", "완성 연보 또는\n원장 3종 등록"),
        ("구조화·확정", "표·셀·메타정보\n초안 확인"),
        ("검수 실행", "필요 항목과\n재사용 옵션 선택"),
        ("결과 확인", "상태·문제 셀·\n판정 근거 확인"),
        ("수정·재검수", "권한 인증 후 수정\n변경 표 재검수"),
        ("다운로드", "표·연보·\n검수 리포트 출력"),
    ]
    xs = [0.52, 2.02, 3.52, 5.02, 6.52, 8.02]
    for i, ((title, body), x) in enumerate(zip(steps, xs), start=1):
        add_round_rect(slide, x, 1.65, 1.36, 1.62, fill=WHITE, line=BORDER, name=f"사용 단계_{i}_{title}")
        add_number_badge(slide, i, x + 0.12, 1.76, fill=NAVY if i < 5 else TEAL)
        add_text(slide, title, x + 0.12, 2.18, 1.12, 0.28, size=10.5, color=NAVY, bold=True, align=PP_ALIGN.CENTER)
        add_text(slide, body, x + 0.10, 2.53, 1.16, 0.50, size=8.6, color=MUTED, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
        if i < len(steps):
            add_arrow(slide, x + 1.39, 2.30, 0.10, 0.28, color=CYAN)

    add_round_rect(slide, 1.02, 3.68, 7.96, 0.93, fill=SKY_2, line="B9D8EA", name="재검수 원칙")
    add_pill(slide, "재검수 원칙", 1.22, 3.91, 1.18, 0.34, fill=NAVY, color=WHITE, size=9, line=None)
    add_rich_text(
        slide,
        [
            {"text": "변경 표", "bold": True, "color": BLUE, "size": 9.4},
            {"text": "는 현재 값으로 다시 검수하고,  ", "size": 9.4},
            {"text": "구조 변경", "bold": True, "color": PURPLE, "size": 9.4},
            {"text": "은 프로파일을 재생성하며,  ", "size": 9.4},
            {"text": "동일 표", "bold": True, "color": TEAL, "size": 9.4},
            {"text": "는 이전 결과를 재사용합니다.", "size": 9.4},
        ],
        2.62,
        3.86,
        6.12,
        0.40,
        valign=MSO_ANCHOR.MIDDLE,
    )
    add_text(
        slide,
        "※ 수정 저장 직후 자동 검수가 실행되는 것은 아니며, 담당자가 ‘검수 실행’을 통해 새 결과를 생성합니다.",
        1.40,
        4.77,
        7.20,
        0.24,
        size=8.2,
        color=MUTED,
        align=PP_ALIGN.CENTER,
    )
    set_notes(
        slide,
        "사용자는 업로드 초안을 확인하고 연보를 확정한 뒤 필요한 검수 항목을 선택합니다. "
        "상세 화면에서 문제 셀과 근거 셀을 함께 확인하고, 수정 권한을 인증해 값을 정정할 수 있습니다. "
        "수정된 통계표는 재검수 필요 상태가 되며 담당자가 검수를 다시 실행합니다.",
    )


def slide_upload(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "업로드", "두 가지 업로드 경로와 공통 구조화", 7, logo_blob, headline="연보 등록")

    routes = [
        (0.56, "A", "완성 연보 새로 업로드", NAVY, "HWPX · Markdown", ["대상 연도", "연보명", "원본 파일"], "업로드 초안"),
        (5.18, "B", "기준 연보에 새 연도 원장 추가", BLUE, "표정보 · 표항목 · 표데이터", ["대상 연도", "기준 연보", "Excel 3종(.xls/.xlsx)"], "다음 연도 초안"),
    ]
    for x, letter, title, accent, file_line, inputs, output in routes:
        add_round_rect(slide, x, 1.42, 4.26, 2.34, fill=WHITE, line=BORDER, name=f"업로드 경로_{letter}")
        add_rect(slide, x, 1.42, 4.26, 0.47, fill=accent, line=None)
        add_circle(slide, x + 0.16, 1.53, 0.25, fill=WHITE, line=None)
        add_text(slide, letter, x + 0.16, 1.53, 0.25, 0.25, size=8.5, color=accent, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE, margin=0)
        add_text(slide, title, x + 0.52, 1.53, 3.50, 0.24, size=11.2, color=WHITE, bold=True)
        add_text(slide, "입력 파일", x + 0.20, 2.10, 0.82, 0.22, size=8.5, color=MUTED, bold=True)
        add_text(slide, file_line, x + 1.10, 2.07, 2.92, 0.27, size=11.0, color=NAVY, bold=True)
        add_text(slide, "공통 입력", x + 0.20, 2.57, 0.82, 0.22, size=8.5, color=MUTED, bold=True)
        add_text(slide, " · ".join(inputs), x + 1.10, 2.54, 2.92, 0.27, size=9.2, color=TEXT)
        add_text(slide, "처리 결과", x + 0.20, 3.03, 0.82, 0.22, size=8.5, color=MUTED, bold=True)
        add_pill(slide, output, x + 1.10, 2.96, 1.62, 0.34, fill=SKY_2 if letter == "A" else TEAL_BG, color=accent if letter == "A" else TEAL, size=9.2, line=None)
        if letter == "A":
            add_text(slide, "화면 기준 지원 형식", x + 2.85, 3.04, 1.10, 0.18, size=7.2, color=MUTED_2, align=PP_ALIGN.RIGHT)

    add_down_arrow(slide, 2.47, 3.82, 0.36, 0.32)
    add_down_arrow(slide, 7.09, 3.82, 0.36, 0.32)
    add_round_rect(slide, 0.82, 4.19, 8.36, 0.63, fill=SKY_2, line="B9D8EA", name="공통 구조화 단계")
    stages = ["파서 선택", "표 번호·좌표·중복 검증", "표·셀·메타정보 DB 저장", "초안 확인 후 연보 확정"]
    sx = [1.00, 2.68, 5.05, 7.25]
    sw = [1.20, 1.96, 1.82, 1.68]
    for idx, (label, x, w) in enumerate(zip(stages, sx, sw)):
        add_text(slide, label, x, 4.38, w, 0.22, size=8.6, color=NAVY, bold=True, align=PP_ALIGN.CENTER)
        if idx < len(stages) - 1:
            add_arrow(slide, x + w + 0.08, 4.39, 0.16, 0.19, color=CYAN)
    add_text(
        slide,
        "판단이 어려운 구조·항목 연결은 확인 필요로 보존하고, 선택한 경우에만 LLM 보조를 적용",
        1.65,
        4.92,
        6.70,
        0.20,
        size=7.9,
        color=MUTED,
        align=PP_ALIGN.CENTER,
    )
    set_notes(
        slide,
        "화면에서는 완성 연보 HWPX 또는 Markdown을 업로드하거나, 기준 연보와 표정보·표항목·표데이터 Excel 3종으로 다음 연도 초안을 만들 수 있습니다. "
        "업로드 결과는 즉시 검수를 끝낸 연보가 아니라 사용자가 확인할 수 있는 초안입니다. 초안 확정 후 별도로 검수를 실행합니다.",
    )


def slide_validation_overview(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "검수", "검수 항목과 판정 방식", 8, logo_blob, headline="검수 체계")

    add_round_rect(slide, 0.52, 1.36, 4.36, 2.42, fill=WHITE, line=BORDER, name="규칙 통계 기반 검수")
    add_rect(slide, 0.52, 1.36, 4.36, 0.43, fill=NAVY, line=None)
    add_text(slide, "규칙·통계 기반 검수", 0.70, 1.47, 3.98, 0.22, size=11.3, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    numeric = [
        (0.72, 1.98, "합계", "행·열 합계, 소계, 명시 산식"),
        (2.77, 1.98, "비율", "구성비·증감액·증감률 포함"),
        (0.72, 2.82, "메타데이터", "단위·기준일·출처 확인"),
        (2.77, 2.82, "이상치", "열별 중앙값·MAD 기반 후보"),
    ]
    for x, y, title, body in numeric:
        add_round_rect(slide, x, y, 1.90, 0.64, fill=SKY_2, line="C5DDEA")
        add_text(slide, title, x + 0.10, y + 0.09, 0.70, 0.20, size=9.5, color=BLUE, bold=True)
        add_text(slide, body, x + 0.72, y + 0.07, 1.08, 0.40, size=8.3, color=TEXT, valign=MSO_ANCHOR.MIDDLE)

    add_round_rect(slide, 5.12, 1.36, 4.36, 2.42, fill=WHITE, line=BORDER, name="언어 검수")
    add_rect(slide, 5.12, 1.36, 4.36, 0.43, fill=BLUE, line=None)
    add_text(slide, "언어 검수", 5.30, 1.47, 4.00, 0.22, size=11.3, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    add_round_rect(slide, 5.35, 1.98, 1.66, 0.84, fill=PURPLE_BG, line=None)
    add_text(slide, "오탈자", 5.49, 2.08, 1.38, 0.22, size=9.7, color=PURPLE, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, "철자·문자 깨짐·\n숫자 표기 후보", 5.47, 2.35, 1.42, 0.34, size=8.2, color=TEXT, align=PP_ALIGN.CENTER)
    add_round_rect(slide, 7.59, 1.98, 1.66, 0.84, fill=TEAL_BG, line=None)
    add_text(slide, "번역", 7.73, 2.08, 1.38, 0.22, size=9.7, color=TEAL, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, "명확한 국·영문 쌍의\n의미 대응 후보", 7.71, 2.35, 1.42, 0.34, size=8.2, color=TEXT, align=PP_ALIGN.CENTER)
    add_arrow(slide, 7.14, 2.24, 0.28, 0.28)
    add_round_rect(slide, 5.48, 3.05, 3.64, 0.45, fill=LIGHT, line=BORDER)
    add_text(slide, "공식 사전  →  문맥 이력  →  선택적 LLM", 5.65, 3.16, 3.30, 0.20, size=8.9, color=NAVY, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, "HWPX 파란색 표기는 별도 검토 후보로 보존", 5.58, 3.55, 3.40, 0.19, size=8.0, color=MUTED, align=PP_ALIGN.CENTER)

    add_text(slide, "검수 결과 상태", 0.62, 4.06, 1.20, 0.23, size=9.2, color=MUTED, bold=True)
    states = [
        (0.62, "1", "정상", "자동 검수에서 문제 없음", TEAL_BG, TEAL),
        (3.67, "2", "확인 필요", "문맥·특이값 등 담당자 판단", AMBER_BG, AMBER),
        (6.72, "3", "오류 의심", "계산 불일치 등 우선 확인", RED_BG, RED),
    ]
    for x, num, title, body, fill, accent in states:
        add_round_rect(slide, x, 4.36, 2.66, 0.61, fill=fill, line=accent)
        add_circle(slide, x + 0.12, 4.49, 0.32, fill=accent)
        add_text(slide, num, x + 0.12, 4.49, 0.32, 0.32, size=9.2, color=WHITE, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE, margin=0)
        add_text(slide, title, x + 0.52, 4.43, 0.80, 0.20, size=9.2, color=accent, bold=True)
        add_text(slide, body, x + 0.52, 4.66, 1.98, 0.20, size=8.0, color=TEXT)

    set_notes(
        slide,
        "합계·비율·메타데이터·이상치는 규칙 또는 통계 기준으로 처리됩니다. 이상치를 LLM 판정 영역으로 설명하지 않도록 주의합니다. "
        "오탈자와 번역은 후보를 먼저 만든 뒤 사전과 문맥 이력을 적용하고, 선택 시 남은 후보에만 LLM을 사용합니다. "
        "상태는 담당자가 무엇을 먼저 확인해야 하는지 보여주는 업무 분류입니다.",
    )


def slide_profile_generation(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "검수 프로파일", "공통·표유형·표별·통계별 규칙을 하나의 실행 명세로 구성", 9, logo_blob, headline="검수 프로파일")

    add_round_rect(slide, 0.68, 1.30, 8.64, 0.47, fill=SKY_2, line="C5DDEA", name="구조 분석 입력")
    add_pill(slide, "구조 서명", 0.88, 1.40, 0.92, 0.27, fill=BLUE, color=WHITE, size=8.3, line=None)
    add_text(
        slide,
        "헤더 행 수 · 행/열 수 · 라벨 열 · 정규화 헤더 · 데이터 행 항목 순서를 분석",
        1.98,
        1.39,
        7.02,
        0.24,
        size=8.9,
        color=NAVY,
        bold=True,
        valign=MSO_ANCHOR.MIDDLE,
    )

    layers = [
        (
            0.55,
            "01",
            "공통 프로파일",
            ["모든 표에 기본 규칙 적용", "단위·기준일·출처 확인", "숫자열의 이상치 적용 가능성 분석"],
            NAVY,
        ),
        (
            2.79,
            "02",
            "표유형 프로파일",
            ["지역형·연도추이형 등 유형 식별", "지역형: 전국계 = 시도별 값 합계", "헤더·행 라벨 구조를 유형 정보로 저장"],
            BLUE,
        ),
        (
            5.03,
            "03",
            "표별 자동 추론",
            ["계·합계·소계와 헤더 계층 분석", "분자·분모·증감·명시 산식 후보 생성", "현재 값 일치율로 후보 신뢰도 검증"],
            PURPLE,
        ),
        (
            7.27,
            "04",
            "통계별 지정 규칙",
            ["통계번호별 검증 규칙을 병합", "자동 후보의 추가·억제·신뢰도 보정", "분할표·고정 셀·가중평균 등 예외 반영"],
            TEAL,
        ),
    ]
    for x, num, title, bullets, accent in layers:
        add_round_rect(slide, x, 1.98, 2.12, 2.29, fill=WHITE, line=accent, name=f"프로파일 계층_{title}")
        add_rect(slide, x, 1.98, 2.12, 0.42, fill=accent, line=None)
        add_text(slide, num, x + 0.13, 2.08, 0.32, 0.20, size=8.4, color=WHITE, bold=True)
        add_text(slide, title, x + 0.48, 2.08, 1.49, 0.20, size=9.4, color=WHITE, bold=True)
        add_bullets(slide, bullets, x + 0.17, 2.60, 1.78, 1.48, size=8.0, gap=5, bullet_color=accent)

    add_round_rect(slide, 0.68, 4.52, 8.64, 0.51, fill=NAVY, line=None, name="프로파일 병합 결과")
    add_text(slide, "병합·중복 제거", 0.94, 4.67, 1.16, 0.18, size=8.5, color=CYAN, bold=True)
    add_text(
        slide,
        "실행 가능한 JSON 명세로 저장  |  동일 표번호+구조서명 우선 재사용  |  구조 변경·미확정 규칙만 선택적 LLM 보조",
        2.18,
        4.64,
        6.87,
        0.22,
        size=8.25,
        color=WHITE,
        bold=True,
        align=PP_ALIGN.CENTER,
    )

    set_notes(
        slide,
        "프로파일은 네 층의 규칙을 순서대로 병합합니다. 공통 규칙은 모든 표의 단위·기준일·출처를 확인하고, 숫자 열에는 이상치 프로파일을 만들 수 있습니다. "
        "표유형 분석은 지역형, 연도추이형, 성별·직급형, 수입·지출·잔액형 등의 구조 신호를 기록하며 현재는 지역형의 전국 합계 템플릿을 직접 적용합니다. "
        "표별 자동 추론은 계·합계·소계 라벨, 헤더 부모·자식 관계, 명시 산식과 현재 값 일치율로 계산 규칙 후보를 만듭니다. "
        "마지막으로 통계번호별 지정 규칙이 자동 후보를 추가·억제·보정하고, 분할표나 고정 셀 관계 같은 예외를 반영합니다. 병합 후 중복을 제거해 JSON 실행 명세로 저장합니다.",
    )


def add_validation_screenshot_body(
    slide,
    *,
    items: list[tuple[str, str]],
    placeholder_title: str,
    placeholder_subtitle: str,
    principle_label: str,
    principle_text: str,
    accent: str,
) -> None:
    add_round_rect(slide, 0.55, 1.95, 2.82, 3.15, fill=WHITE, line=BORDER, name="검수 범위")
    add_rect(slide, 0.55, 1.95, 2.82, 0.46, fill=accent, line=None)
    add_text(slide, "검수 범위", 0.80, 2.08, 2.32, 0.22, size=11.5, color=WHITE, bold=True, align=PP_ALIGN.CENTER)

    for index, (title, detail) in enumerate(items, start=1):
        y = 2.55 + (index - 1) * 0.50
        add_round_rect(slide, 0.76, y, 2.40, 0.42, fill=LIGHT, line=None, name=f"검수 범위_{title}")
        add_pill(slide, f"{index:02d}", 0.86, y + 0.08, 0.40, 0.25, fill=accent, color=WHITE, size=8.3, line=None)
        add_text(slide, title, 1.36, y + 0.045, 1.62, 0.19, size=10.0, color=NAVY, bold=True)
        add_text(slide, detail, 1.36, y + 0.225, 1.62, 0.16, size=8.1, color=MUTED)

    add_round_rect(slide, 0.76, 4.64, 2.40, 0.28, fill=SKY_2 if accent == BLUE else TEAL_BG, line=None)
    add_text(slide, principle_label, 0.90, 4.70, 0.76, 0.16, size=8.6, color=accent, bold=True)
    add_text(slide, principle_text, 1.58, 4.69, 1.43, 0.17, size=8.0, color=TEXT, align=PP_ALIGN.RIGHT)

    add_image_placeholder(
        slide,
        3.62,
        1.95,
        5.83,
        2.70,
        title=placeholder_title,
        subtitle=placeholder_subtitle,
        name=f"이미지 삽입_{placeholder_title}",
    )
    add_round_rect(slide, 3.62, 4.78, 5.83, 0.32, fill=SKY_2 if accent == BLUE else TEAL_BG, line=None)
    add_text(slide, "이미지 확인 항목", 3.86, 4.86, 1.08, 0.17, size=8.4, color=accent, bold=True)
    add_text(
        slide,
        "오류 위치  ·  현재값  ·  재계산값  ·  판정 근거",
        5.02,
        4.85,
        4.13,
        0.18,
        size=8.5,
        color=TEXT,
        bold=True,
        align=PP_ALIGN.CENTER,
    )


def slide_sum_validation(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "합계 검수", "표의 방향·계층·명시 산식에 따라 구성값을 다시 합산", 10, logo_blob, headline="합계 검수")

    add_validation_screenshot_body(
        slide,
        items=[
            ("행 방향 합계", "같은 행의 하위 열 합산"),
            ("열 방향 합계·소계", "세부 행·시도별 값 합산"),
            ("명시 산식", "a+b·a-b 관계 실행"),
            ("셀·분할표 관계", "고정 셀·반복 구역 합산"),
        ],
        placeholder_title="합계 검수 화면 이미지 삽입",
        placeholder_subtitle="오류 셀과 재계산 근거가 함께 보이는 실제 화면 권장",
        principle_label="판정 원칙",
        principle_text="평균 열 제외 · 허용오차 적용",
        accent=BLUE,
    )

    set_notes(
        slide,
        "합계 규칙은 네 범주입니다. 행 방향 합계는 같은 행의 구성 열을 더하고, 열 방향 합계와 소계는 세부 행을 더합니다. 지역형 표는 전국계와 시도별 값을 연결합니다. "
        "헤더에 c=a+b 또는 a-b 같은 식이 있으면 명시 산식으로 실행하며 증감액도 이 방식으로 계산합니다. 반복 구역이나 분할표는 셀 관계 또는 표 간 행 합계를 통계별 규칙으로 지정할 수 있습니다. "
        "합계 후보를 만들 때 비율, 증감률, 평균처럼 더하면 안 되는 열은 제외합니다. 현재값과 기대값은 저장된 허용오차 안에서 비교하며, 판정할 수 없는 비숫자 값은 건너뜁니다.",
    )


def slide_ratio_validation(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "비율 검수", "분자·분모 관계를 재계산하며 증감액·증감률도 함께 확인", 11, logo_blob, headline="비율·증감 검수")

    add_validation_screenshot_body(
        slide,
        items=[
            ("동일 행 비율", "분자 열 ÷ 분모 열 × 100"),
            ("전체 대비 구성비", "지역값 ÷ 총계값 × 100"),
            ("행 간·원단위", "건당·인당 값 재계산"),
            ("증감·지정식", "증감액·증감률·가중평균"),
        ],
        placeholder_title="비율·증감 검수 화면 이미지 삽입",
        placeholder_subtitle="분자·분모와 판정 결과가 함께 보이는 실제 화면 권장",
        principle_label="집계 원칙",
        principle_text="총계 재계산 · 분모 0 제외",
        accent=TEAL,
    )

    set_notes(
        slide,
        "비율 검수는 같은 행의 분자 열과 분모 열, 전체 합계 행을 분모로 하는 구성비, 그리고 같은 연도 열에서 서로 다른 분자·분모 행을 계산하는 방식으로 구분됩니다. "
        "건당·인당 값은 배율 1의 원단위 비율로 처리합니다. 증감액은 당해 값에서 전년 값을 빼고, 증감률은 그 차이를 전년 값으로 나눈 뒤 100을 곱합니다. "
        "특정 통계의 가중평균이나 분할표 관계는 통계번호별 지정 규칙으로 실행합니다. 총계와 소계의 비율은 개별 비율을 합산하지 않고 합계 분자와 합계 분모로 다시 계산합니다. "
        "분모 0과 비숫자 값은 판정을 건너뛰고, 표시 자릿수와 배율에 맞춘 허용오차로 현재값을 비교합니다.",
    )


def slide_language_candidates(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "오탈자·번역 검수", "검수 후보는 먼저 좁혀서 생성", 12, logo_blob, headline="언어 후보 생성")

    add_round_rect(slide, 0.60, 1.40, 8.80, 0.62, fill=WHITE, line=BORDER)
    add_number_badge(slide, 1, 0.76, 1.55, fill=NAVY)
    add_text(slide, "언어 위치 수집", 1.18, 1.52, 1.35, 0.24, size=10.3, color=NAVY, bold=True)
    add_text(slide, "표 제목 · 대제목 · 하위 표 제목 · 헤더 · 국문/영문 텍스트 셀", 2.66, 1.49, 6.45, 0.30, size=9.2, color=TEXT, valign=MSO_ANCHOR.MIDDLE)
    add_down_arrow(slide, 4.84, 2.07, 0.32, 0.26)
    add_round_rect(slide, 1.02, 2.36, 7.96, 0.62, fill=LIGHT, line=BORDER)
    add_number_badge(slide, 2, 1.18, 2.51, fill=BLUE)
    add_text(slide, "불필요 항목 제외", 1.60, 2.48, 1.55, 0.24, size=10.3, color=BLUE, bold=True)
    add_text(slide, "숫자만 있는 값·불필요 메타정보 제외  /  긴 문장은 적정 길이로 분할", 3.28, 2.45, 5.42, 0.30, size=9.0, color=TEXT, valign=MSO_ANCHOR.MIDDLE)
    add_down_arrow(slide, 4.84, 3.03, 0.32, 0.26)

    add_round_rect(slide, 1.10, 3.35, 3.70, 1.12, fill=PURPLE_BG, line=None, name="오탈자 후보")
    add_bullets(slide, ["국문·영문 철자와 문자 깨짐", "중복 문장부호·숫자 구분기호·단위 표기"], 1.28, 3.87, 3.25, 0.48, size=8.3, gap=2, bullet_color=PURPLE)
    add_round_rect(slide, 5.20, 3.35, 3.70, 1.12, fill=SKY_2, line=None, name="번역 후보")
    add_bullets(slide, ["명확한 한·영 병기쌍 또는 혼합 문맥만 생성", "한국어 단독 셀을 ‘영문 누락’으로 단정하지 않음"], 5.38, 3.87, 3.25, 0.48, size=8.3, gap=2)

    # Some non-Google renderers expose a legacy theme effect as a thin rule in
    # this title band. Opaque editable title strips keep the cards consistent
    # across PowerPoint, Keynote and Quick Look without rasterizing content.
    add_rect(slide, 1.10, 3.43, 3.70, 0.35, fill=PURPLE_BG, line=None, name="오탈자 제목 배경")
    add_text(slide, "오탈자 후보", 1.30, 3.52, 1.20, 0.24, size=10.8, color=PURPLE, bold=True)
    add_rect(slide, 5.20, 3.43, 3.70, 0.35, fill=SKY_2, line=None, name="번역 제목 배경")
    add_text(slide, "번역 후보", 5.40, 3.52, 1.20, 0.24, size=10.8, color=BLUE, bold=True)

    add_round_rect(slide, 1.10, 4.68, 7.80, 0.34, fill=NAVY, line=None)
    add_text(slide, "HWPX 파란색 표기는 별도 출처로 보존  |  원문은 자동 수정하지 않고 후보·권고값만 제공", 1.30, 4.74, 7.40, 0.20, size=8.2, color=WHITE, bold=True, align=PP_ALIGN.CENTER)

    set_notes(
        slide,
        "언어 검수는 모든 텍스트를 곧바로 LLM에 보내지 않습니다. 제목과 표 내부의 의미 있는 위치를 수집하고 숫자 전용 값 등 불필요한 후보를 제외합니다. "
        "오탈자 후보는 넓게 만들되, 번역 후보는 명확한 국·영문 대응이 있는 경우에만 생성해 과도한 오류 판단을 줄입니다. "
        "판정 결과는 자동 수정이 아니라 담당자에게 원문과 권고값을 제시하는 방식입니다.",
    )


def slide_dictionary_cache(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "오탈자·번역 검수", "사전·문맥 이력·선택적 LLM의 단계적 적용", 13, logo_blob, headline="언어 검수")

    steps = [
        (1, "공식·승인 사전 확인", "정확 일치 항목을 우선 처리", NAVY),
        (2, "문맥 이력 재사용", "계보/선택 run + 지문 일치", BLUE),
        (3, "남은 후보만 LLM", "동일 문맥 후보를 구조화 배치", PURPLE),
        (4, "응답 검증·저장", "후보 ID·현재 원문 일치 확인", TEAL),
    ]
    for idx, (num, title, body, accent) in enumerate(steps):
        y = 1.40 + idx * 0.82
        add_round_rect(slide, 0.54, y, 3.52, 0.61, fill=WHITE, line=accent, name=f"언어 검수 단계_{num}")
        add_circle(slide, 0.68, y + 0.13, 0.34, fill=accent)
        add_text(slide, str(num), 0.68, y + 0.13, 0.34, 0.34, size=9.2, color=WHITE, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE, margin=0)
        add_text(slide, title, 1.10, y + 0.10, 1.70, 0.22, size=9.5, color=accent, bold=True)
        add_text(slide, body, 1.10, y + 0.33, 2.72, 0.21, size=8.2, color=TEXT)
        if idx < 3:
            add_down_arrow(slide, 2.11, y + 0.63, 0.28, 0.16, color=accent)

    add_round_rect(slide, 4.40, 1.40, 5.05, 1.22, fill=SKY_2, line="C5DDEA", name="사전 구성 방식")
    add_text(slide, "사전 구성·갱신", 4.62, 1.58, 1.35, 0.23, size=10.6, color=BLUE, bold=True)
    add_text(slide, "검수 실행 시 다음 자료를 모아 출처와 상태를 유지", 6.02, 1.58, 3.12, 0.21, size=8.4, color=MUTED)
    glossary_items = ["기본 용어", "공식 번역", "기관·행정구역", "연보 한·영 병기"]
    gx = [4.64, 5.74, 7.10, 8.34]
    gw = [0.92, 1.18, 1.08, 0.88]
    for label, x, w in zip(glossary_items, gx, gw):
        add_pill(slide, label, x, 2.06, w, 0.29, fill=WHITE, color=NAVY, size=7.9, line="B9D8EA")

    add_round_rect(slide, 4.40, 2.84, 5.05, 1.84, fill=LIGHT, line=BORDER, name="문맥 지문 기반 검수 이력")
    add_rich_text(
        slide,
        [
            {"text": "‘캐시’", "size": 10.8, "bold": True, "color": PURPLE},
            {"text": " = 문맥 지문 기반 검수 이력", "size": 10.8, "bold": True, "color": NAVY},
        ],
        4.62,
        3.02,
        3.70,
        0.26,
    )
    fingerprint = ["검수 유형", "원문·위치", "표 제목·단위", "행·열 라벨", "주변 문맥", "프롬프트·모델", "사전 근거"]
    positions = [(4.64, 3.48), (5.64, 3.48), (6.68, 3.48), (7.83, 3.48), (4.64, 3.91), (5.75, 3.91), (7.13, 3.91)]
    widths = [0.84, 0.86, 1.02, 0.96, 0.93, 1.20, 0.82]
    for label, (x, y), w in zip(fingerprint, positions, widths):
        add_pill(slide, label, x, y, w, 0.29, fill=WHITE, color=BLUE, size=7.7, line="B9D8EA")
    add_text(slide, "보고서 계보 또는 사용자가 선택한 이전 실행에서만 재사용 · 전역 텍스트 캐시가 아님", 4.64, 4.38, 4.56, 0.20, size=7.9, color=MUTED, align=PP_ALIGN.CENTER)

    add_round_rect(slide, 0.96, 4.86, 8.08, 0.24, fill=AMBER_BG, line=None)
    add_text(slide, "LLM 미사용·키 부재·응답 누락 시 후보는 ‘재검수 필요’로 유지하며, 자동으로 원문을 바꾸지 않습니다.", 1.18, 4.88, 7.64, 0.19, size=8.2, color=AMBER, bold=True, align=PP_ALIGN.CENTER)

    set_notes(
        slide,
        "사전은 외부 사이트를 실시간 조회하는 방식이 아니라 번들 자료, 공식 기관·행정구역 자료와 연보 내부의 한·영 병기를 검수 시 구성합니다. "
        "캐시는 전역 문자열 캐시가 아니라 검수 유형, 원문, 위치, 주변 문맥, 프롬프트와 모델 버전, 사전 근거까지 포함한 지문이 일치할 때만 재사용하는 검수 이력입니다. "
        "남은 후보만 선택적으로 LLM에 보내며 응답 연결이 확인된 경우에만 저장합니다.",
    )


def slide_metadata_outlier(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "메타데이터·이상치 검수", "누락과 통계적 특이값을 확인 대상으로 제시", 14, logo_blob, headline="메타데이터·이상치")

    add_round_rect(slide, 0.55, 1.38, 4.20, 3.42, fill=WHITE, line=BORDER, name="메타데이터 검수")
    add_rect(slide, 0.55, 1.38, 4.20, 0.45, fill=NAVY, line=None)
    add_text(slide, "메타데이터 검수", 0.75, 1.50, 3.80, 0.22, size=11.2, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    meta_rows = [
        ("단위", "누락 여부 + 저장 프로파일 기준 단위와 일치"),
        ("기준일", "필수 정보 입력 여부"),
        ("출처", "필수 정보 입력 여부"),
    ]
    for idx, (label, body) in enumerate(meta_rows):
        y = 2.05 + idx * 0.72
        add_round_rect(slide, 0.80, y, 3.70, 0.54, fill=SKY_2 if idx == 0 else LIGHT, line="C5DDEA" if idx == 0 else BORDER)
        add_pill(slide, label, 0.95, y + 0.12, 0.70, 0.30, fill=BLUE if idx == 0 else WHITE, color=WHITE if idx == 0 else NAVY, size=8.3, line=None if idx == 0 else BORDER)
        add_text(slide, body, 1.82, y + 0.09, 2.48, 0.34, size=8.2, color=TEXT, valign=MSO_ANCHOR.MIDDLE)
    add_round_rect(slide, 0.88, 4.36, 3.54, 0.25, fill=AMBER_BG, line=None)
    add_text(slide, "현재 자동 검수 범위: 위 3개 필드의 누락과 단위 기준", 1.02, 4.39, 3.26, 0.18, size=7.9, color=AMBER, bold=True, align=PP_ALIGN.CENTER)

    add_round_rect(slide, 5.05, 1.38, 4.40, 3.42, fill=WHITE, line=BORDER, name="이상치 검수")
    add_rect(slide, 5.05, 1.38, 4.40, 0.45, fill=BLUE, line=None)
    add_text(slide, "이상치 검수", 5.25, 1.50, 4.00, 0.22, size=11.2, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, "동일 숫자 열(관측치 5개 이상)", 5.34, 2.03, 3.82, 0.23, size=9.4, color=NAVY, bold=True, align=PP_ALIGN.CENTER)
    add_rect(slide, 5.58, 3.08, 3.18, 0.02, fill=BORDER, line=None)
    dots = [
        (5.88, 9, TEAL),
        (6.35, 10, TEAL),
        (6.82, 10, TEAL),
        (7.29, 11, TEAL),
        (8.42, 43, RED),
    ]
    for x, value, color in dots:
        add_circle(slide, x, 2.88, 0.24, fill=color)
        add_text(slide, str(value), x - 0.06, 3.18, 0.36, 0.20, size=8.0, color=color, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, "중앙값", 6.45, 2.54, 0.75, 0.20, size=8.0, color=TEAL, bold=True, align=PP_ALIGN.CENTER)
    add_down_arrow(slide, 6.66, 2.72, 0.24, 0.15, color=TEAL)
    add_pill(slide, "확인 필요", 8.04, 2.41, 0.92, 0.30, fill=RED_BG, color=RED, size=7.8, line=RED)
    add_bullets(
        slide,
        ["중앙값과 MAD(중앙절대편차)로 이탈 정도 계산", "합계·소계 행은 제외하고 표당 최대 1건 제시"],
        5.42,
        3.66,
        3.64,
        0.55,
        size=8.2,
        gap=2,
        bullet_color=BLUE,
    )
    add_round_rect(slide, 5.42, 4.36, 3.64, 0.25, fill=TEAL_BG, line=None)
    add_text(slide, "통계적 특이값은 오류를 의미하지 않음", 5.64, 4.39, 3.20, 0.18, size=8.0, color=TEAL, bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, "담당자는 출처·단위·업무 맥락을 함께 확인한 뒤 최종 판단", 1.65, 4.96, 6.70, 0.18, size=8.0, color=MUTED, align=PP_ALIGN.CENTER)

    set_notes(
        slide,
        "현재 메타데이터 자동 검수는 단위, 기준일, 출처의 누락과 저장된 프로파일 기준 단위의 일치 여부로 제한됩니다. "
        "이상치는 같은 숫자 열에서 값이 5개 이상일 때 중앙값과 MAD로 편차를 계산하고, 보수적인 임계값을 넘는 후보를 표당 최대 한 건 제시합니다. "
        "이상치는 오류 확정이 아니라 확인 필요 상태입니다.",
    )


def slide_edit_revalidation(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "수정·재검수", "통계별 편집 보호와 변경 범위 기반 재검수", 15, logo_blob, headline="수정·재검수")

    add_round_rect(slide, 0.52, 1.38, 4.20, 2.16, fill=WHITE, line=BORDER, name="수정 가능 요소")
    add_rect(slide, 0.52, 1.38, 4.20, 0.43, fill=NAVY, line=None)
    add_text(slide, "수정 가능 요소", 0.72, 1.49, 3.80, 0.22, size=11, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    edit_items = [
        (0.76, 2.04, "기본정보", "통계 코드·국/영문 제목·분류"),
        (2.70, 2.04, "표 구조", "헤더·행/열 추가·삭제·순서"),
        (0.76, 2.76, "내용", "국/영문 셀 값·각주"),
        (2.70, 2.76, "메타데이터", "단위·기준일·출처·담당정보"),
    ]
    for x, y, title, body in edit_items:
        add_round_rect(slide, x, y, 1.74, 0.56, fill=LIGHT, line=BORDER)
        add_text(slide, title, x + 0.09, y + 0.09, 0.72, 0.20, size=9.0, color=BLUE, bold=True)
        add_text(slide, body, x + 0.80, y + 0.05, 0.84, 0.40, size=7.8, color=TEXT, valign=MSO_ANCHOR.MIDDLE)

    add_round_rect(slide, 5.02, 1.38, 4.46, 2.16, fill=WHITE, line=BORDER, name="편집 보호")
    add_rect(slide, 5.02, 1.38, 4.46, 0.43, fill=BLUE, line=None)
    add_text(slide, "통계별 편집 보호", 5.22, 1.49, 4.06, 0.22, size=11, color=WHITE, bold=True, align=PP_ALIGN.CENTER)
    security = [(5.30, "비밀번호 인증"), (6.78, "편집 토큰"), (8.26, "수정 저장")]
    for idx, (x, label) in enumerate(security):
        add_round_rect(slide, x, 2.10, 1.12, 0.56, fill=SKY_2 if idx < 2 else TEAL_BG, line="C5DDEA" if idx < 2 else "B8DED2")
        add_text(slide, label, x + 0.06, 2.26, 1.00, 0.22, size=9.0, color=BLUE if idx < 2 else TEAL, bold=True, align=PP_ALIGN.CENTER)
        if idx < 2:
            add_arrow(slide, x + 1.19, 2.24, 0.20, 0.26, color=CYAN)
    add_text(slide, "비밀번호는 salt를 적용한 PBKDF2 해시로 저장", 5.48, 2.94, 3.54, 0.20, size=8.2, color=MUTED, align=PP_ALIGN.CENTER)
    add_text(slide, "※ 계정·역할 기반 권한관리와 세션 만료는 향후 개선 과제", 5.42, 3.21, 3.66, 0.20, size=7.9, color=AMBER, align=PP_ALIGN.CENTER)

    add_text(slide, "수정 후 재검수 로직", 0.56, 3.76, 1.82, 0.26, size=10.8, color=NAVY, bold=True)
    re_steps = [
        (0.58, "수정 저장", NAVY),
        (2.42, "기존 결과\n‘재검수 필요’", AMBER),
        (4.48, "담당자\n검수 실행", BLUE),
        (6.56, "변경 표\n현재 값 검수", PURPLE),
        (8.20, "새 실행 결과\n갱신", TEAL),
    ]
    widths = [1.35, 1.55, 1.55, 1.38, 1.20]
    for idx, ((x, label, accent), w) in enumerate(zip(re_steps, widths)):
        add_round_rect(slide, x, 4.10, w, 0.62, fill=WHITE, line=accent, line_width=1.1)
        add_text(slide, label, x + 0.06, 4.20, w - 0.12, 0.38, size=8.8, color=accent, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
        if idx < len(re_steps) - 1:
            next_x = re_steps[idx + 1][0]
            add_arrow(slide, x + w + 0.10, 4.26, max(0.16, next_x - (x + w) - 0.20), 0.30, color=BLUE)
    add_round_rect(slide, 1.10, 4.87, 7.80, 0.26, fill=LIGHT, line=None)
    add_rich_text(
        slide,
        [
            {"text": "값 변경", "size": 8.1, "bold": True, "color": BLUE},
            {"text": " 기존 프로파일로 재계산   |   ", "size": 8.1},
            {"text": "구조 변경", "size": 8.1, "bold": True, "color": BLUE},
            {"text": " 새 프로파일 생성   |   ", "size": 8.1},
            {"text": "동일 표", "size": 8.1, "bold": True, "color": TEAL},
            {"text": " 이전 결과 재사용", "size": 8.1},
        ],
        1.28,
        4.90,
        7.44,
        0.18,
        align=PP_ALIGN.CENTER,
    )

    set_notes(
        slide,
        "수정 화면에서는 표 기본정보, 헤더와 행·열 구조, 국·영문 셀 값, 주요 메타정보를 수정할 수 있습니다. "
        "통계별 비밀번호를 확인한 뒤 편집 토큰을 발급하며, 비밀번호 원문은 저장하지 않습니다. "
        "저장 즉시 이전 검수 결과는 활성 화면에서 제외되고 재검수 필요 상태가 됩니다. 담당자가 검수를 실행하면 변경 표는 현재 값으로 다시 판정되고 동일 표는 이전 결과를 재사용합니다.",
    )


def slide_download(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "다운로드", "업무 목적에 맞춘 3가지 산출물", 16, logo_blob, headline="산출물 다운로드")

    cards = [
        (0.55, "01", "표 단위", "개별 표 검토·자료 공유", ["선택한 통계표와 하위 표", "국·영문 헤더 및 셀 내용", "단위·기준일·출처 등 메타정보"]),
        (3.66, "02", "연보 단위", "연보 취합·후속 분석", ["전체 또는 선택 통계표", "통계표를 찾기 위한 목차", "통계표·하위 표별 개별 시트"]),
        (6.77, "03", "검수 리포트", "오류 확인·결과 보고", ["검수 내역과 판정 근거", "문제·근거 셀이 강조된 표", "메타데이터 감사 자료"]),
    ]
    for x, num, title, purpose, bullets in cards:
        add_round_rect(slide, x, 1.48, 2.68, 3.00, fill=WHITE, line=BORDER, name=f"다운로드_{title}")
        add_rect(slide, x, 1.48, 2.68, 0.52, fill=NAVY, line=None)
        add_text(slide, num, x + 0.18, 1.61, 0.40, 0.21, size=8.8, color=CYAN, bold=True)
        add_text(slide, title, x + 0.60, 1.60, 1.88, 0.23, size=11.5, color=WHITE, bold=True)
        add_text(slide, purpose, x + 0.26, 2.24, 2.16, 0.28, size=11.0, color=BLUE, bold=True, align=PP_ALIGN.CENTER)
        add_rect(slide, x + 0.28, 2.73, 2.12, 0.015, fill=BORDER, line=None)
        add_bullets(slide, bullets, x + 0.28, 2.98, 2.12, 1.12, size=9.0, gap=7, bullet_color=BLUE)
    add_round_rect(slide, 0.96, 4.70, 8.08, 0.34, fill=SKY_2, line="C5DDEA")
    add_text(slide, "필요한 범위와 검수 상태를 선택하여 업무 목적에 맞는 산출물을 생성", 1.22, 4.76, 7.56, 0.20, size=9.0, color=NAVY, bold=True, align=PP_ALIGN.CENTER)

    set_notes(
        slide,
        "표 단위 산출물은 선택한 통계표와 하위 표, 국·영문 내용과 메타정보를 함께 제공합니다. 연보 단위 산출물은 전체 또는 선택 표를 목차와 개별 시트 구조로 구성합니다. "
        "검수 리포트는 오류 의심과 확인 필요 상태를 대상으로 검수 내역, 문제·근거 셀이 강조된 표, 메타데이터 감사 자료를 제공합니다.",
    )


def slide_expected_effects(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "기대효과", "반복 검수는 시스템이 지원하고, 최종 판단은 담당자가 수행", 17, logo_blob, headline="기대효과")

    effects = [
        ("01", "반복 대조 업무 축소", "합계·비율·증감 관계를 같은 기준으로 반복 검수", BLUE),
        ("02", "검수 기준의 일관성", "프로파일·용어 사전·검수 이력을 다음 연도에 재사용", TEAL),
        ("03", "오류 추적성 강화", "문제 셀과 근거 셀, 현재값·기대값·산식을 함께 확인", PURPLE),
        ("04", "수정 결과의 최신성", "수정 후 기존 결과를 구분하고 변경 범위 중심으로 재검수", AMBER),
    ]
    for idx, (num, title, body, accent) in enumerate(effects):
        y = 1.43 + idx * 0.86
        add_round_rect(slide, 0.54, y, 5.56, 0.68, fill=WHITE, line=BORDER)
        add_rect(slide, 0.54, y, 0.055, 0.68, fill=accent, line=None)
        add_text(slide, num, 0.76, y + 0.17, 0.38, 0.20, size=8.4, color=accent, bold=True)
        add_text(slide, title, 1.20, y + 0.10, 2.10, 0.24, size=10.3, color=TEXT, bold=True)
        add_text(slide, body, 1.20, y + 0.37, 4.56, 0.22, size=8.5, color=MUTED)

    add_round_rect(slide, 6.43, 1.43, 3.02, 3.44, fill=NAVY, line=None, name="업무 변화 강조")
    add_text(slide, "업무 변화", 6.70, 1.78, 2.48, 0.24, size=10, color="B7CCE6", bold=True, align=PP_ALIGN.CENTER)
    add_text(slide, "담당자는\n의미 판단과\n최종 확인에 집중", 6.78, 2.29, 2.30, 1.30, size=18, color=WHITE, bold=True, align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
    add_rect(slide, 7.35, 3.86, 1.18, 0.02, fill=CYAN, line=None)
    add_text(slide, "자동화는 반복 검증과\n검토 우선순위 제시를 지원합니다.", 6.84, 4.08, 2.18, 0.47, size=8.2, color="DCE8F5", align=PP_ALIGN.CENTER)
    add_text(slide, "※ 정량 효과는 실제 운영 자료를 축적한 뒤 측정·제시", 0.84, 4.90, 5.04, 0.20, size=8.0, color=MUTED, align=PP_ALIGN.CENTER)

    set_notes(
        slide,
        "기대효과는 아직 실증된 정량 수치가 아니라 시스템 적용을 통해 기대하는 업무 변화입니다. "
        "반복 계산과 대조를 줄이고, 검수 기준과 이력을 축적해 연도별 일관성을 높일 수 있습니다. "
        "담당자는 자동 판정이 어려운 의미·정책 판단과 최종 승인에 더 집중할 수 있습니다.",
    )


def slide_improvements(slide, logo_blob: bytes) -> None:
    clear_slide(slide)
    add_header(slide, "향후 개선 과제", "공공기관 운영을 위한 우선 보완사항", 18, logo_blob, headline="향후 개선 과제")

    table_shape = slide.shapes.add_table(6, 4, Inches(0.50), Inches(1.34), Inches(9.00), Inches(3.50))
    table_shape.name = "향후 개선 과제 표"
    table = table_shape.table
    widths = [1.28, 2.05, 4.83, 0.84]
    for col, width in zip(table.columns, widths):
        col.width = Inches(width)
    headers = ["개선 영역", "현행 수준", "개선 방향", "우선"]
    for c, text in enumerate(headers):
        set_table_cell(table.cell(0, c), text, size=9.3, color=WHITE, bold=True, fill=NAVY, align=PP_ALIGN.CENTER)
    rows = [
        ("권한·보안", "통계별 비밀번호·편집 토큰", "기관 통합인증·역할 권한, 최초 변경, 세션 만료·실패 잠금", "높음"),
        ("검수 투명성", "결과·근거 중심 표시", "프로파일 승인, 적용/미적용 범위, AI 근거·모델·비용 관리", "높음"),
        ("정확도 확장", "메타·이상치 범위 제한", "날짜·출처 품질, 분야별·시계열 이상치, 담당자 피드백 반영", "중간"),
        ("이력·재검수", "저장 후 담당자가 재실행", "셀 단위 변경 전후 이력·되돌리기, 원클릭 재검수·알림", "중간"),
        ("운영·출력", "대규모 처리·발간 출력 보완", "진행률·재시도 사유, 서버 일괄 출력, 공식 발간 형식 지원", "중간"),
    ]
    for r, row in enumerate(rows, start=1):
        fill = LIGHT if r % 2 else WHITE
        for c, text in enumerate(row):
            align = PP_ALIGN.CENTER if c in (0, 3) else PP_ALIGN.LEFT
            color = RED if c == 3 and text == "높음" else (AMBER if c == 3 else TEXT)
            set_table_cell(table.cell(r, c), text, size=8.1 if c in (1, 2) else 8.6, color=color, bold=(c in (0, 3)), fill=fill, align=align)
    add_round_rect(slide, 1.14, 4.96, 7.72, 0.22, fill=NAVY, line=None)
    add_text(slide, "확실한 규칙부터 적용하고 검증 이력을 축적하여, 예외·판단 영역을 단계적으로 확대", 1.38, 4.97, 7.24, 0.19, size=8.3, color=WHITE, bold=True, align=PP_ALIGN.CENTER)

    set_notes(
        slide,
        "공공기관 운영 전환을 위해서는 계정·역할 기반 권한관리, 초기 비밀번호 정책과 세션 만료 등 보안 보완이 우선 필요합니다. "
        "또한 프로파일 적용 범위와 AI 판정 근거를 관리자 화면에서 확인하고 승인할 수 있어야 합니다. "
        "정확도가 검증된 규칙부터 단계적으로 적용하고 담당자 피드백과 운영 지표를 축적해 범위를 확대하는 접근이 적절합니다.",
    )


def build(source: Path, output: Path) -> None:
    prs = Presentation(source)
    if len(prs.slides) < 14:
        raise RuntimeError("원본 발표자료는 최소 14개 슬라이드여야 합니다.")
    logo_blob = find_logo_blob(prs)

    prs.core_properties.title = "통계연보 검수 보조 시스템"
    prs.core_properties.subject = "통계연보 검수 업무 개선 및 시스템 주요 기능"
    prs.core_properties.author = "행정안전부 데이터정보화담당관"
    prs.core_properties.keywords = "통계연보, 검수, 합계, 비율, 오탈자, 번역, 메타데이터, 이상치"

    style_cover(prs.slides[0])
    replace_text(prs.slides[1], "수백개의", "수백 개의")
    replace_page_number(prs.slides[1], 2)
    add_text(
        prs.slides[1],
        "반복 확인과 오류 누락으로 검수 시간과 업무 부담이 증가",
        0.50,
        1.44,
        8.90,
        0.32,
        size=12.0,
        color=MUTED,
        valign=MSO_ANCHOR.MIDDLE,
        name="슬라이드 부제목",
    )
    set_notes(
        prs.slides[1],
        "기존 검수는 수백 개 표를 담당자가 반복 대조해야 하고, 표 구조가 달라 검수 기준과 지식을 재사용하기 어렵습니다. "
        "계산 오류와 오탈자를 서로 다른 방식으로 확인하면서 검수 시간과 누락 위험도 커질 수 있습니다.",
    )
    slide_comparison(prs.slides[2], logo_blob)
    reflow_body_for_tall_header(prs.slides[2])

    # The draft's slides 4–14 use a Google-exported content layout whose empty
    # placeholders remain visually active after their slide shapes are removed.
    # Keep slides 1–3, then build all revised material on the deck's true BLANK
    # layout so no legacy placeholder can cover editable content.
    slide_ids = prs.slides._sldIdLst
    while len(prs.slides) > 3:
        slide_id = slide_ids[3]
        prs.part.drop_rel(slide_id.rId)
        del slide_ids[3]

    builders = [
        slide_problem_examples,
        slide_system_overview,
        slide_user_flow,
        slide_upload,
        slide_validation_overview,
        slide_profile_generation,
        slide_sum_validation,
        slide_ratio_validation,
        slide_language_candidates,
        slide_dictionary_cache,
        slide_metadata_outlier,
        slide_edit_revalidation,
        slide_download,
        slide_expected_effects,
        slide_improvements,
    ]
    blank_layout = prs.slide_layouts[10]
    for layout_shape in list(blank_layout.shapes):
        element = layout_shape._element
        element.getparent().remove(element)
    for builder in builders:
        slide = prs.slides.add_slide(blank_layout)
        # All visible header/footer elements are added explicitly below. Hide
        # the Google-exported master placeholders, whose decorative effect can
        # otherwise appear as a stray blue rule in non-Google renderers.
        slide._element.set("showMasterSp", "0")
        builder(slide, logo_blob)
        if builder not in {slide_sum_validation, slide_ratio_validation}:
            reflow_body_for_tall_header(slide)

    force_font_family(prs)
    output.parent.mkdir(parents=True, exist_ok=True)
    prs.save(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="기존 초안 PPTX")
    parser.add_argument("output", type=Path, help="생성할 개선본 PPTX")
    args = parser.parse_args()
    build(args.source, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
