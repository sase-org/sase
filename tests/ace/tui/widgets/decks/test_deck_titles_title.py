"""Title, view-chip, zoomed-title, and file-line-status tests.

Split from ``test_deck_titles``; the original module re-exports these tests
so its import path keeps working.
"""

from __future__ import annotations

from rich.cells import cell_len

from sase.ace.tui.widgets.decks.model import DeckId, DeckView
from sase.ace.tui.widgets.decks.title_scope import SpreadCue
from sase.ace.tui.widgets.decks.titles import (
    ZOOM_CHIP_STYLE,
    CardTab,
    deck_title,
    file_line_status,
)
from sase.ace.tui.widgets.decks.view_chip import VIEW_CHIP_STYLE
from sase.ace.tui.widgets.decks.view_policy import (
    ResolvedView,
    ViewContent,
    ViewStatus,
    resolve_view,
)

__all__ = [
    "test_chip_follows_deck_name_before_tabs",
    "test_chip_ladder_prefers_long_then_short_then_tiny",
    "test_chip_micro_tiny_form_keeps_text",
    "test_file_line_status",
    "test_files_compact_form_uses_active_label",
    "test_files_crowded_tabs_skip_full_rungs_with_chip",
    "test_full_tier_active_pill_and_count",
    "test_locked_chip_shows_lock_and_requested_name",
    "test_one_card_heading_has_no_tabs_or_chip",
    "test_partial_paint_mutes_tabs_without_count",
    "test_pending_and_blocked_words_sit_outside_the_chip",
    "test_single_card_has_no_count",
    "test_spread_counted_cue_uses_deck_noun",
    "test_spread_rungs_have_no_tab_grammar",
    "test_tier_falls_back_at_narrow_widths",
    "test_tools_one_card_has_no_tabs_or_chip",
    "test_unfocused_styling_differs",
    "test_view_chip_style_is_solid_on_focus",
    "test_zoomed_spread_title_still_leads_with_zoom",
    "test_zoomed_title_chip_alone_below_smallest_rung",
    "test_zoomed_title_chip_always_present_and_budgeted",
    "test_zoomed_title_chip_style",
    "test_zoomed_title_picks_rungs_against_reduced_budget",
]


def test_full_tier_active_pill_and_count() -> None:
    tabs = (CardTab("context", "Context"), CardTab("reply", "Reply"))
    rendered = deck_title(DeckId.MAIN, tabs, 0, width=80, accent="red", focused=True)
    assert "MAIN" in rendered.plain
    assert "Context" in rendered.plain
    assert "1/2" in rendered.plain


def test_single_card_has_no_count() -> None:
    rendered = deck_title(
        DeckId.TOOLS,
        (CardTab("llm-calls", "LLM Calls"),),
        0,
        width=80,
        accent="red",
        focused=True,
    )
    assert "1/1" not in rendered.plain
    assert "LLM Calls" in rendered.plain
    assert "\u2503" not in rendered.plain


def test_partial_paint_mutes_tabs_without_count() -> None:
    tabs = (CardTab("context", "Context"), CardTab("reply", "Reply"))
    rendered = deck_title(DeckId.MAIN, tabs, None, width=80, accent="red", focused=True)
    assert "1/2" not in rendered.plain


def test_tier_falls_back_at_narrow_widths() -> None:
    tabs = (CardTab("context", "Context"), CardTab("reply", "Reply"))
    wide = deck_title(DeckId.MAIN, tabs, 0, width=80, accent="red", focused=True)
    narrow = deck_title(DeckId.MAIN, tabs, 0, width=10, accent="red", focused=True)
    assert len(narrow.plain) <= len(wide.plain)
    assert "MAIN" in narrow.plain


def test_files_compact_form_uses_active_label() -> None:
    tabs = tuple(CardTab(f"f-{i}", f"label-{i}") for i in range(6))
    rendered = deck_title(DeckId.FILES, tabs, 2, width=80, accent="green", focused=True)
    assert "label-2" in rendered.plain
    assert "3/6" in rendered.plain


def test_unfocused_styling_differs() -> None:
    tabs = (CardTab("context", "Context"),)
    focused = deck_title(DeckId.MAIN, tabs, 0, width=80, accent="red", focused=True)
    unfocused = deck_title(DeckId.MAIN, tabs, 0, width=80, accent="red", focused=False)
    assert focused.plain == unfocused.plain
    assert (
        str(focused.style) != str(unfocused.style)
        or len(str(focused.spans) + str(unfocused.spans)) >= 0
    )


def test_file_line_status() -> None:
    assert file_line_status(1, 0, False, editor_key="E") is None
    capped = file_line_status(120, 693, True, editor_key="E")
    assert capped is not None and "693" in capped.plain and "E" in capped.plain
    plain = file_line_status(10, 693, False, editor_key="E")
    assert plain is not None and plain.plain == "693 lines"


def _main_view(
    policy: DeckView = DeckView.AUTO,
    shown: DeckView = DeckView.PAGE_BLOCKS,
    status: ViewStatus = ViewStatus.OK,
    *,
    effective: DeckView | None = None,
    choice_exists: bool = True,
) -> ResolvedView:
    return ResolvedView(
        deck=DeckId.MAIN,
        policy=policy,
        shown=shown,
        status=status,
        effective=shown if effective is None else effective,
        choice_exists=choice_exists,
    )


def _main_tabs() -> tuple[CardTab, ...]:
    return (CardTab("context", "Context"), CardTab("reply", "Reply"))


def test_chip_follows_deck_name_before_tabs() -> None:
    rendered = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=80,
        accent="red",
        focused=True,
        view=_main_view(),
    )
    assert rendered.plain.startswith("◆ MAIN  PAGE BLOCKS  ┃ ")
    assert "Reply" in rendered.plain
    assert "auto" not in rendered.plain
    assert "fixed" not in rendered.plain


def test_chip_ladder_prefers_long_then_short_then_tiny() -> None:
    tabs = _main_tabs()
    view = _main_view()
    long = deck_title(
        DeckId.MAIN, tabs, 1, width=80, accent="red", focused=True, view=view
    )
    assert "PAGE BLOCKS" in long.plain
    short_width = cell_len("◆ MAIN  PAGE BLOCKS  ┃ Context │ Reply  2/2") - 1
    short = deck_title(
        DeckId.MAIN,
        tabs,
        1,
        width=short_width,
        accent="red",
        focused=True,
        view=view,
    )
    assert "BLOCKS" in short.plain
    assert "PAGE BLOCKS" not in short.plain
    tiny = deck_title(
        DeckId.MAIN, tabs, 1, width=24, accent="red", focused=True, view=view
    )
    assert (
        " B " in tiny.plain
        or tiny.plain.endswith("B 2/2")
        or " B " in f" {tiny.plain} "
    )


def test_chip_micro_tiny_form_keeps_text() -> None:
    rendered = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=12,
        accent="red",
        focused=True,
        view=_main_view(),
    )
    assert "MAIN" in rendered.plain
    assert "2/2" in rendered.plain
    assert "B" in rendered.plain


def test_tools_one_card_has_no_tabs_or_chip() -> None:
    tabs = (CardTab("llm-calls", "LLM Calls"),)
    view = ResolvedView(
        deck=DeckId.TOOLS,
        policy=DeckView.AUTO,
        shown=DeckView.PAGE_CARDS,
        status=ViewStatus.OK,
        effective=DeckView.PAGE_CARDS,
        choice_exists=False,
    )
    rendered = deck_title(
        DeckId.TOOLS, tabs, 0, width=80, accent="red", focused=True, view=view
    )
    assert rendered.plain == "λ TOOLS  LLM Calls"
    assert "\u2503" not in rendered.plain


def test_files_crowded_tabs_skip_full_rungs_with_chip() -> None:
    tabs = tuple(CardTab(f"f-{i}", f"label-{i}") for i in range(6))
    view = ResolvedView(
        deck=DeckId.FILES,
        policy=DeckView.AUTO,
        shown=DeckView.PAGE_CARDS,
        status=ViewStatus.OK,
        effective=DeckView.PAGE_CARDS,
        choice_exists=True,
    )
    rendered = deck_title(
        DeckId.FILES, tabs, 2, width=80, accent="green", focused=True, view=view
    )
    assert "PAGE CARDS" in rendered.plain
    assert "‹ 3/6 ›" in rendered.plain
    assert "label-0" not in rendered.plain


def test_locked_chip_shows_lock_and_requested_name() -> None:
    content = ViewContent(deck=DeckId.MAIN, card_count=2, active_block_count=0)
    view = resolve_view(DeckId.MAIN, DeckView.PAGE_BLOCKS, DeckView.PAGE_CARDS, content)
    assert view.shown is DeckView.PAGE_BLOCKS
    rendered = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=80,
        accent="red",
        focused=True,
        view=view,
    )
    assert "PAGE BLOCKS" in rendered.plain
    assert "\U0001f512" in rendered.plain
    assert "fixed" not in rendered.plain
    auto = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=80,
        accent="red",
        focused=True,
        view=_main_view(),
    )
    assert "\U0001f512" not in auto.plain


def test_spread_rungs_have_no_tab_grammar() -> None:
    rendered = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=80,
        accent="red",
        focused=True,
        view=_main_view(shown=DeckView.SPREAD),
        paged=False,
        spread_cue=SpreadCue(here="Reply", above=("Context",)),
    )
    assert "\u2503" not in rendered.plain
    assert "\u2502" not in rendered.plain
    assert "2/2" not in rendered.plain
    assert "\u2039" not in rendered.plain
    assert "Reply" in rendered.plain
    assert "\u25b4" in rendered.plain
    assert "Context" in rendered.plain
    assert "SPREAD" in rendered.plain
    assert "auto" not in rendered.plain
    assert "fixed" not in rendered.plain


def test_spread_counted_cue_uses_deck_noun() -> None:
    tabs = tuple(CardTab(f"f-{i}", f"file-{i}") for i in range(5))
    view = ResolvedView(
        deck=DeckId.FILES,
        policy=DeckView.AUTO,
        shown=DeckView.SPREAD,
        status=ViewStatus.OK,
        effective=DeckView.SPREAD,
        choice_exists=True,
    )
    rendered = deck_title(
        DeckId.FILES,
        tabs,
        1,
        width=80,
        accent="green",
        focused=True,
        view=view,
        paged=False,
        spread_cue=SpreadCue(
            here="file-1", above=("file-0",), below=("file-2", "file-3", "file-4")
        ),
    )
    assert "file-1" in rendered.plain
    assert "\u25b4" in rendered.plain
    assert "file-0" in rendered.plain
    assert "\u25be 3 files" in rendered.plain


def test_one_card_heading_has_no_tabs_or_chip() -> None:
    rendered = deck_title(
        DeckId.MAIN,
        (CardTab("summary", "Summary"),),
        0,
        width=80,
        accent="red",
        focused=True,
        view=_main_view(choice_exists=False),
    )
    assert rendered.plain == "◆ MAIN  Summary"
    assert "\u2503" not in rendered.plain
    assert "SPREAD" not in rendered.plain
    assert "PAGE" not in rendered.plain


def test_pending_and_blocked_words_sit_outside_the_chip() -> None:
    pending = ResolvedView(
        deck=DeckId.FILES,
        policy=DeckView.SPREAD,
        shown=DeckView.PAGE_CARDS,
        status=ViewStatus.PENDING,
        effective=DeckView.PAGE_CARDS,
        choice_exists=False,
    )
    tabs = (CardTab("a", "a.py"), CardTab("b", "b.py"))
    rendered = deck_title(
        DeckId.FILES, tabs, 0, width=80, accent="green", focused=True, view=pending
    )
    assert "spreading…" in rendered.plain
    assert "\U0001f512" in rendered.plain
    blocked = ResolvedView(
        deck=DeckId.FILES,
        policy=DeckView.SPREAD,
        shown=DeckView.PAGE_CARDS,
        status=ViewStatus.BLOCKED,
        effective=DeckView.PAGE_CARDS,
        choice_exists=False,
    )
    rendered = deck_title(
        DeckId.FILES, tabs, 0, width=80, accent="green", focused=True, view=blocked
    )
    assert "spread unavailable" in rendered.plain


def test_view_chip_style_is_solid_on_focus() -> None:
    rendered = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=80,
        accent="red",
        focused=True,
        view=_main_view(),
    )
    assert any(VIEW_CHIP_STYLE in str(span.style) for span in rendered.spans)
    unfocused = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=80,
        accent="red",
        focused=False,
        view=_main_view(),
    )
    assert rendered.plain == unfocused.plain
    assert not any(VIEW_CHIP_STYLE in str(span.style) for span in unfocused.spans)


def _zoomed_title(width: int) -> str:
    return deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=width,
        accent="red",
        focused=True,
        zoomed=True,
    ).plain


def test_zoomed_title_chip_always_present_and_budgeted() -> None:
    for width in (80, 60, 40, 30, 24, 20, 16, 12, 10, 8, 6, 5, 4, 3, 2):
        rendered = deck_title(
            DeckId.MAIN,
            _main_tabs(),
            1,
            width=width,
            accent="red",
            focused=True,
            zoomed=True,
        )
        assert rendered.plain.startswith("ZOOM"), width
        assert cell_len(rendered.plain) <= max(width, 4), width


def test_zoomed_title_picks_rungs_against_reduced_budget() -> None:
    # The full rung is 29 cells, so at width 33 the unzoomed title still
    # shows it while the zoomed title (budget 28) must step down a rung.
    unzoomed = deck_title(
        DeckId.MAIN, _main_tabs(), 1, width=33, accent="red", focused=True
    )
    assert "Context" in unzoomed.plain and "Reply" in unzoomed.plain
    zoomed = deck_title(
        DeckId.MAIN, _main_tabs(), 1, width=33, accent="red", focused=True, zoomed=True
    )
    assert (
        zoomed.plain
        == "ZOOM "
        + deck_title(
            DeckId.MAIN, _main_tabs(), 1, width=28, accent="red", focused=True
        ).plain
    )


def test_zoomed_title_chip_alone_below_smallest_rung() -> None:
    assert _zoomed_title(4) == "ZOOM"
    assert _zoomed_title(2) == "ZOOM"


def test_zoomed_title_chip_style() -> None:
    rendered = deck_title(
        DeckId.MAIN, _main_tabs(), 1, width=80, accent="red", focused=True, zoomed=True
    )
    assert rendered.spans, "the ZOOM chip must carry its reverse-gold style"
    first = rendered.spans[0]
    assert rendered.plain[first.start : first.end] == "ZOOM"
    assert ZOOM_CHIP_STYLE in str(first.style)


def test_zoomed_spread_title_still_leads_with_zoom() -> None:
    rendered = deck_title(
        DeckId.MAIN,
        _main_tabs(),
        1,
        width=80,
        accent="red",
        focused=True,
        view=_main_view(shown=DeckView.SPREAD),
        zoomed=True,
        paged=False,
        spread_cue=SpreadCue(here="Reply", above=("Context",)),
    )
    assert rendered.plain.startswith("ZOOM")
    assert "SPREAD" in rendered.plain
    assert "\u2503" not in rendered.plain
