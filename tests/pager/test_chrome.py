"""Tests for the pager's pure chrome/footer rendering helpers."""

from __future__ import annotations

from rich.console import Console

from sase.pager._chrome import (
    _format_char_count,
    _section_accent,
    _section_icon,
    footer_legend,
    goto_command_line,
    section_rule,
    subject_line,
)
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection

_CONSOLE = Console(color_system="truecolor")


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


def test_subject_line_shows_the_syntax_hint_when_it_fits() -> None:
    section = _file_section("a.py")
    document = PagerDocument(sections=(section,), title="a.py", origin=PagerOrigin.FILE)

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=80,
        syntax_hint="py",
    )

    assert "· py" in line.plain


def test_subject_line_omits_the_syntax_hint_when_absent() -> None:
    section = _file_section("a.py")
    document = PagerDocument(sections=(section,), title="a.py", origin=PagerOrigin.FILE)

    line = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=80,
        syntax_hint=None,
    )

    assert "· py" not in line.plain


def test_subject_line_drops_the_syntax_hint_before_the_subject_at_narrow_width() -> (
    None
):
    section = _file_section("a.py")
    document = PagerDocument(sections=(section,), title="a.py", origin=PagerOrigin.FILE)

    without_hint = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=20,
        syntax_hint=None,
    )
    with_hint = subject_line(
        document,
        section,
        section_index=1,
        section_total=1,
        scroll_percent=0,
        char_count=10,
        width=20,
        syntax_hint="py",
    )

    assert "· py" not in with_hint.plain
    assert with_hint.plain == without_hint.plain


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


def test_footer_legend_names_trail_sheet_when_history_exists() -> None:
    line = footer_legend(section_total=1, trail_forward_count=2)

    assert "<tab> forward" in line.plain
    assert "^I forward" not in line.plain
    assert "? trail/keys" in line.plain
    assert "? keys" not in line.plain


def test_footer_legend_shows_follow_only_when_labels_exist() -> None:
    no_labels = footer_legend(section_total=1, label_count=0)
    labels = footer_legend(section_total=1, label_count=3)

    assert "follow" not in no_labels.plain
    assert "0-9a-z follow" in labels.plain


def test_footer_legend_promotes_pending_prefix_over_follow_hint() -> None:
    line = footer_legend(section_total=1, label_count=60, pending_prefix="Z")

    assert "Z… link" in line.plain
    assert "follow" not in line.plain


def test_goto_command_line_idle_shows_range_and_gold_sigil() -> None:
    line = goto_command_line(
        digits="",
        line_count=12,
        section_title=None,
        section_kind=None,
        width=80,
    )

    assert line.plain.startswith(":")
    assert "line 1-12" in line.plain
    assert line.get_style_at_offset(_CONSOLE, 0).bold is True


def test_goto_command_line_typing_keeps_digits_white() -> None:
    line = goto_command_line(
        digits="4",
        line_count=12,
        section_title=None,
        section_kind=None,
        width=80,
    )

    assert ":4" in line.plain
    assert "out of range" not in line.plain
    style = line.get_style_at_offset(_CONSOLE, 1)
    assert style.bold is not True


def test_goto_command_line_invalid_restyles_digits_and_range() -> None:
    line = goto_command_line(
        digits="0",
        line_count=12,
        section_title="alpha.py",
        section_kind="file",
        width=80,
    )

    assert "out of range · 1-12" in line.plain
    assert "alpha.py" not in line.plain
    style = line.get_style_at_offset(_CONSOLE, 1)
    assert style.bold is True


def test_goto_command_line_multi_section_shows_glyph_and_title() -> None:
    line = goto_command_line(
        digits="",
        line_count=30,
        section_title="alpha.py",
        section_kind="file",
        width=80,
    )

    assert _section_icon("file") in line.plain
    assert "alpha.py" in line.plain
    assert "line 1-30" in line.plain


def test_goto_command_line_truncates_title_before_dropping_the_range() -> None:
    line = goto_command_line(
        digits="",
        line_count=12,
        section_title="very-long-section-title.py",
        section_kind="file",
        width=28,
    )

    assert "line 1-12" in line.plain
    assert "very-long-section-title.py" not in line.plain
    assert "…" in line.plain
