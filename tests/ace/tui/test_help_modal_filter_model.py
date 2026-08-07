"""Pure unit tests for the Help panel's live keymap filter model."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.help_modal.bindings import Sections, cls_bindings
from sase.ace.tui.modals.help_modal.filter_model import (
    balance_split,
    filter_sections,
    matches_title,
    tokenize,
)
from sase.ace.tui.widgets._completion_match_highlight import append_highlighted

_SECTIONS: Sections = [
    (
        "Beads Pane",
        [
            ("b", "Jump to Beads pane"),
            ("B", "Toggle Beads filter"),
        ],
    ),
    (
        "Copy Mode · Agents",
        [
            ("%a", "Copy agent id"),
            ("%t", "Copy agent title"),
        ],
    ),
    (
        "Agent Actions",
        [
            ("K", "Kill selected running agent"),
            ("m", "Mark/unmark current agent"),
        ],
    ),
    (
        "Prompt Input",
        [
            ("Ctrl+D", "Delete saved completion entry"),
            ("Ctrl+L", "Reveal/complete / accept"),
        ],
    ),
]


def test_tokenize_splits_on_whitespace() -> None:
    assert tokenize("  copy   beads ") == ("copy", "beads")
    assert tokenize("") == ()
    assert tokenize("   ") == ()


def test_empty_and_whitespace_queries_are_inactive() -> None:
    for query in ("", "   "):
        result = filter_sections(_SECTIONS, query)
        assert result.active is False
        assert result.sections == ()
        assert result.keymap_count == 0
        assert result.section_count == 0
        assert result.relaxed is False


def test_section_name_match_pulls_in_every_row() -> None:
    result = filter_sections(_SECTIONS, "beads")

    assert result.active is True
    assert [section.name for section in result.sections] == ["Beads Pane"]
    section = result.sections[0]
    assert [row.key for row in section.rows] == ["b", "B"]
    assert section.name_runs != ()


def test_multi_token_and_matches_section_name_order_independently() -> None:
    for query in ("copy agents", "agents copy"):
        result = filter_sections(_SECTIONS, query)
        assert [section.name for section in result.sections] == ["Copy Mode · Agents"]
        assert [row.key for row in result.sections[0].rows] == ["%a", "%t"]


def test_multi_token_and_across_section_name_and_description() -> None:
    result = filter_sections(_SECTIONS, "kill agent")

    assert [section.name for section in result.sections] == ["Agent Actions"]
    rows = result.sections[0].rows
    assert [row.key for row in rows] == ["K"]
    assert rows[0].description == "Kill selected running agent"


def test_token_matching_only_the_key_display() -> None:
    result = filter_sections(_SECTIONS, "ctrl+d")

    assert [section.name for section in result.sections] == ["Prompt Input"]
    row = result.sections[0].rows[0]
    assert row.key == "Ctrl+D"
    assert row.key_runs != ()
    assert row.description_runs == ()


def test_token_matching_only_the_description() -> None:
    result = filter_sections(_SECTIONS, "reveal")

    assert [section.name for section in result.sections] == ["Prompt Input"]
    row = result.sections[0].rows[0]
    assert row.key == "Ctrl+L"
    assert row.key_runs == ()
    assert row.description_runs != ()


def test_contiguous_match_is_not_relaxed() -> None:
    result = filter_sections(_SECTIONS, "beads")

    assert result.relaxed is False
    assert result.keymap_count > 0


def test_initialism_with_no_contiguous_match_relaxes_to_scattered() -> None:
    result = filter_sections(_SECTIONS, "bp")

    assert result.relaxed is True
    assert [section.name for section in result.sections] == ["Beads Pane"]
    assert result.keymap_count == 2


def test_zero_matches_returns_empty_result() -> None:
    result = filter_sections(_SECTIONS, "qqqqq")

    assert result.active is True
    assert result.sections == ()
    assert result.keymap_count == 0
    assert result.section_count == 0
    assert result.relaxed is False


def test_matches_title_for_query_panels() -> None:
    assert matches_title("Saved Queries", "saved") is not None
    assert matches_title("Saved Queries", "history") is None
    assert matches_title("Query History", "history") is not None
    assert matches_title("Query History", "saved") is None
    assert matches_title("Saved Queries", "") is None


def test_balance_split_balances_line_counts() -> None:
    sections: Sections = [
        ("Alpha", [("a1", "row one"), ("a2", "row two")]),
        ("Beta", [("b1", "row three")]),
        ("Gamma", [("g1", "row four"), ("g2", "row five"), ("g3", "row six")]),
    ]
    result = filter_sections(sections, "row")
    assert result.section_count == 3
    assert result.keymap_count == 6

    assert balance_split(result.sections) == 2
    assert balance_split(result.sections, lead_lines=10) == 0


def test_balance_split_handles_zero_and_one_section() -> None:
    assert balance_split(()) == 0

    result = filter_sections([("Alpha", [("a1", "row one")])], "row")
    assert balance_split(result.sections) == 0


def test_runs_are_within_bounds_against_production_sections() -> None:
    sections = cls_bindings(load_keymap_registry({}))
    result = filter_sections(sections, "beads")
    assert result.keymap_count > 0

    for section in result.sections:
        _assert_runs_render_safely(section.name, section.name_runs)
        for row in section.rows:
            _assert_runs_render_safely(row.key, row.key_runs)
            _assert_runs_render_safely(row.description, row.description_runs)


def _assert_runs_render_safely(text: str, runs: tuple[tuple[int, int], ...]) -> None:
    for start, end in runs:
        assert 0 <= start < end <= len(text)

    rendered = Text()
    append_highlighted(rendered, text, runs, base_style="")
    assert rendered.plain == text
