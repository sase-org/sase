"""Footer-legend and goto-command-line tests for the pager."""

from __future__ import annotations

from sase.pager._chrome import footer_legend, goto_command_line
from sase.pager._chrome_sections import section_icon

from ._chrome_helpers import CONSOLE


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

    assert "^I forward" in line.plain
    assert "<tab> forward" not in line.plain
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


def test_footer_legend_names_other_pane_arm() -> None:
    line = footer_legend(section_total=1, label_count=3, pending_action="other")

    assert "^W… other pane" in line.plain
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
    assert line.get_style_at_offset(CONSOLE, 0).bold is True


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
    style = line.get_style_at_offset(CONSOLE, 1)
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
    style = line.get_style_at_offset(CONSOLE, 1)
    assert style.bold is True


def test_goto_command_line_multi_section_shows_glyph_and_title() -> None:
    line = goto_command_line(
        digits="",
        line_count=30,
        section_title="alpha.py",
        section_kind="file",
        width=80,
    )

    assert section_icon("file") in line.plain
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


def test_footer_shows_a_single_edit_verb() -> None:
    verbs = [("( v23", ""), (") v25", ""), ("@", "timeline"), ("=", "diff")]
    pinned = footer_legend(
        section_total=1, label_count=4, history_pinned=True, time_verbs=verbs
    )
    assert "E edit now" in pinned.plain
    assert pinned.plain.count("E edit") == 1

    unpinned = footer_legend(section_total=1, label_count=4, time_verbs=verbs)
    assert "E edit" in unpinned.plain
    assert "E edit now" not in unpinned.plain
    assert unpinned.plain.count("E edit") == 1
