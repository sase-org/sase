"""Pure filter/score/format tests for the command palette modal.

Split from ``tests.test_command_palette_modal``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from sase.ace.tui.modals.command_palette_modal import (
    _build_count_text,
    _build_position_text,
    _build_row_text,
    _filter_specs as filter_specs,
    _render_gauge,
    _score_match,
)

from tests._command_palette_modal_helpers import make_spec

__all__ = [
    "test_build_count_text_filtered_plural",
    "test_build_count_text_singular",
    "test_build_count_text_unfiltered_plural",
    "test_build_position_text_contains_fraction_and_accent_style",
    "test_build_row_text_includes_key_label_and_category",
    "test_filter_specs_bare_key_filter_returns_all_in_order",
    "test_filter_specs_empty_query_returns_all_in_order",
    "test_filter_specs_excludes_non_matches",
    "test_filter_specs_is_stable_on_ties",
    "test_filter_specs_key_filter_does_not_match_text_metadata",
    "test_filter_specs_key_filter_matches_app_binding_alternatives",
    "test_filter_specs_key_filter_matches_display_chord",
    "test_filter_specs_key_filter_matches_raw_keys_and_chords",
    "test_filter_specs_key_filter_prefix_is_case_insensitive",
    "test_render_gauge_clamps_position_to_range",
    "test_render_gauge_handles_single_and_empty_totals",
    "test_render_gauge_top_middle_bottom",
    "test_score_match_alias_substring",
    "test_score_match_empty_query_is_truthy",
    "test_score_match_label_outranks_key",
    "test_score_match_prefix_outranks_substring",
    "test_score_match_zero_when_no_match",
]


def test_score_match_zero_when_no_match() -> None:
    s = make_spec("app.refresh", "Refresh tab")
    assert _score_match(s, "zzznever") == 0


def test_score_match_prefix_outranks_substring() -> None:
    a = make_spec("app.refresh", "Refresh tab")
    b = make_spec("app.kill_agent", "Kill / dismiss agent (refresh)")
    sa = _score_match(a, "refresh")
    sb = _score_match(b, "refresh")
    assert sa > sb


def test_score_match_label_outranks_key() -> None:
    label_match = make_spec("app.next", "Next entry", key_display="z")
    key_match = make_spec("app.kill_agent", "Kill agent", key_display="next")
    assert _score_match(label_match, "next") > _score_match(key_match, "next")


def test_score_match_alias_substring() -> None:
    s = make_spec("app.refresh", "Refresh tab", aliases=("reload",))
    assert _score_match(s, "reload") > 0


def test_score_match_empty_query_is_truthy() -> None:
    s = make_spec("app.refresh", "Refresh tab")
    assert _score_match(s, "") > 0


def test_filter_specs_is_stable_on_ties() -> None:
    a = make_spec("app.a", "Alpha")
    b = make_spec("app.b", "Bravo")
    c = make_spec("app.c", "Alpha-2")
    out = filter_specs([a, b, c], "alpha")
    # Both a and c have the same prefix-match score; catalog order
    # decides their relative order.
    assert [s.id for s in out] == ["app.a", "app.c"]


def test_filter_specs_excludes_non_matches() -> None:
    a = make_spec("app.refresh", "Refresh tab")
    b = make_spec("app.kill_agent", "Kill agent")
    out = filter_specs([a, b], "refresh")
    assert [s.id for s in out] == ["app.refresh"]


def test_filter_specs_empty_query_returns_all_in_order() -> None:
    a = make_spec("app.refresh", "Refresh")
    b = make_spec("app.next", "Next")
    out = filter_specs([a, b], "")
    assert [s.id for s in out] == ["app.refresh", "app.next"]


def test_filter_specs_key_filter_matches_raw_keys_and_chords() -> None:
    a = make_spec("app.down", "Move down", key_display="j", key_sequence=("j",))
    b = make_spec(
        "leader.jump",
        "Jump to notification",
        key_display=",j",
        key_sequence=("comma", "j"),
    )
    c = make_spec("app.journal", "Journal", key_display="x", key_sequence=("x",))

    out = filter_specs([a, b, c], "key:j")
    assert [s.id for s in out] == ["app.down", "leader.jump"]


def test_filter_specs_key_filter_matches_display_chord() -> None:
    a = make_spec(
        "leader.agent_run_log",
        "Agent run log",
        key_display=",A",
        key_sequence=("comma", "A"),
    )
    b = make_spec("app.task", "Task list", key_display="x", key_sequence=("x",))

    out = filter_specs([a, b], "key:,A")
    assert [s.id for s in out] == ["leader.agent_run_log"]


def test_filter_specs_key_filter_matches_app_binding_alternatives() -> None:
    a = make_spec(
        "app.open_command_palette",
        "Open command palette",
        key_display=";",
        key_sequence=("semicolon",),
    )
    b = make_spec("app.refresh", "Refresh", key_display="r", key_sequence=("r",))
    c = make_spec(
        "app.open_command_line",
        "Command Line",
        key_display=":",
        key_sequence=("colon",),
    )

    assert [s.id for s in filter_specs([a, b, c], "key:;")] == [
        "app.open_command_palette"
    ]
    assert [s.id for s in filter_specs([a, b, c], "key:semicolon")] == [
        "app.open_command_palette"
    ]
    # After the flip ``:`` addresses the Command Line, not the palette.
    assert [s.id for s in filter_specs([a, b, c], "key::")] == ["app.open_command_line"]


def test_filter_specs_key_filter_does_not_match_text_metadata() -> None:
    a = make_spec(
        "app.refresh",
        "Refresh tab",
        key_display="r",
        key_sequence=("r",),
        category="Display",
        aliases=("reload",),
    )

    assert filter_specs([a], "key:refresh") == []
    assert filter_specs([a], "key:display") == []
    assert filter_specs([a], "key:reload") == []


def test_filter_specs_key_filter_prefix_is_case_insensitive() -> None:
    a = make_spec("app.quit", "Quit", key_display="Ctrl+D", key_sequence=("ctrl+d",))
    b = make_spec("app.refresh", "Refresh", key_display="r", key_sequence=("r",))

    out = filter_specs([a, b], " KEY:ctrl+d ")
    assert [s.id for s in out] == ["app.quit"]


def test_filter_specs_bare_key_filter_returns_all_in_order() -> None:
    a = make_spec("app.refresh", "Refresh")
    b = make_spec("app.next", "Next")
    out = filter_specs([a, b], " key: ")
    assert [s.id for s in out] == ["app.refresh", "app.next"]


def test_build_row_text_includes_key_label_and_category() -> None:
    s = make_spec("app.refresh", "Refresh tab", key_display="r", category="Display")
    text = _build_row_text(s).plain
    assert "r" in text
    assert "Refresh tab" in text
    assert "[Display]" in text


def test_build_count_text_unfiltered_plural() -> None:
    assert _build_count_text(72, 72).plain == "72 commands"


def test_build_count_text_filtered_plural() -> None:
    assert _build_count_text(12, 72).plain == "12 of 72 commands"


def test_build_count_text_singular() -> None:
    assert _build_count_text(1, 1).plain == "1 command"
    assert _build_count_text(0, 1).plain == "0 of 1 command"


def test_render_gauge_top_middle_bottom() -> None:
    top, top_idx = _render_gauge(1, 9, 9)
    middle, middle_idx = _render_gauge(5, 9, 9)
    bottom, bottom_idx = _render_gauge(9, 9, 9)

    assert top_idx == 0
    assert top == "●━━━━━━━━"
    assert middle_idx == 4
    assert middle == "━━━━●━━━━"
    assert bottom_idx == 8
    assert bottom == "━━━━━━━━●"


def test_render_gauge_handles_single_and_empty_totals() -> None:
    single, single_idx = _render_gauge(1, 1, 9)
    empty, empty_idx = _render_gauge(1, 0, 9)

    assert single_idx == 0
    assert single == "●━━━━━━━━"
    assert empty_idx == -1
    assert empty == "━━━━━━━━━"


def test_render_gauge_clamps_position_to_range() -> None:
    low, low_idx = _render_gauge(-10, 9, 9)
    high, high_idx = _render_gauge(99, 9, 9)

    assert low_idx == 0
    assert high_idx == 8
    assert 0 <= low_idx < 9
    assert 0 <= high_idx < 9
    assert low == "●━━━━━━━━"
    assert high == "━━━━━━━━●"


def test_build_position_text_contains_fraction_and_accent_style() -> None:
    text = _build_position_text(5, 72, "#87D7FF")

    assert "5/72" in text.plain
    styles = [str(span.style).lower() for span in text.spans]
    assert any("bold" in style and "#87d7ff" in style for style in styles)
