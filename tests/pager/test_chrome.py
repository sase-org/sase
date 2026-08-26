"""Tests for the pager's pure chrome/footer rendering helpers."""

from __future__ import annotations

from sase.pager._chrome import (
    _format_char_count,
    _section_accent,
    _section_icon,
    footer_legend,
    section_rule,
    subject_line,
)
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection


def _bead_section(title: str = "sase-uk.3: The reading surface") -> PagerSection:
    return PagerSection(
        identity="bead:sase-uk.3",
        title=title,
        kind="bead",
        body="some detail",
        subject_ref="bead:sase-uk.3",
    )


def _file_section(title: str = "artifact_links.py") -> PagerSection:
    return PagerSection(
        identity=f"file:/tmp/{title}",
        title=title,
        kind="file",
        body="line one\nline two\n",
        subject_ref=f"file:/tmp/{title}",
    )


def test_section_icon_and_accent_use_the_artifacts_tables() -> None:
    assert _section_icon("bead") == "◈"
    assert _section_icon("file") == "▤"
    assert _section_accent("bead") == "#D787FF"
    assert _section_accent("file") == "#FFAF5F"


def test_section_icon_and_accent_fall_back_for_unknown_kinds() -> None:
    assert _section_icon("diff") == "◆"
    assert _section_accent("diff") == "#AFAFAF"


def test_format_char_count_scales_with_magnitude() -> None:
    assert _format_char_count(88) == "88c"
    assert _format_char_count(1_234) == "1.2Kc"
    assert _format_char_count(2_500_000) == "2.5Mc"


def test_subject_line_omits_position_for_a_single_section_document() -> None:
    section = _bead_section()
    document = PagerDocument(
        sections=(section,),
        title="sase-uk.3 · The reading surface",
        origin=PagerOrigin.BEAD,
    )

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=41,
        char_count=88,
        width=80,
    )

    assert "◈" in line.plain
    assert document.title in line.plain
    assert "1/1" not in line.plain
    assert "41%" in line.plain
    assert "⌘ 88c" in line.plain


def test_subject_line_shows_position_and_current_section_title_when_multi() -> None:
    sections = (_file_section("a.py"), _file_section("b.py"), _file_section("c.py"))
    document = PagerDocument(
        sections=sections, title="3 files", origin=PagerOrigin.FILE
    )

    line = subject_line(
        document,
        sections[1],
        section_index=2,
        section_total=3,
        scroll_percent=12,
        char_count=42,
        width=80,
    )

    assert "▤" in line.plain
    assert "3 files" in line.plain
    assert "b.py" in line.plain
    assert "2/3" in line.plain
    assert "12%" in line.plain


def test_subject_line_pads_to_the_requested_width_when_it_fits() -> None:
    section = _bead_section()
    document = PagerDocument(
        sections=(section,),
        title="sase-uk.3 · The reading surface",
        origin=PagerOrigin.BEAD,
    )

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=0,
        width=80,
    )

    assert len(line.plain) == 80


def test_section_rule_shape_matches_the_design_doc() -> None:
    section = _file_section("artifact_links.py")

    line = section_rule(section, index=2, total=3, width=80)

    assert line.plain.startswith("━━ 2/3 ━ ▤ artifact_links.py")
    assert line.plain.endswith("━")
    assert len(line.plain) == 80


def test_footer_legend_hides_entity_nav_for_a_single_section_document() -> None:
    line = footer_legend(section_total=1)

    assert "^N/^P" not in line.plain
    assert "/ search" in line.plain
    assert "? keys" in line.plain
    assert "q close" in line.plain


def test_footer_legend_shows_entity_nav_for_a_multi_section_document() -> None:
    line = footer_legend(section_total=3)

    assert "^N/^P entity" in line.plain
