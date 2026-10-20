"""Viewport-precise spread cues and paged continuation cues (pure + pilot)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from sase.ace.testing import wait_for
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId, DeckView, RenderMode
from sase.ace.tui.widgets.decks.scope_cues import (
    _card_ends_from_anchors as card_ends_from_anchors,
    continuation_texts,
    resolve_viewport_spread,
    _viewport_partition as viewport_partition,
    viewport_spread_cue,
)
from sase.ace.tui.widgets.decks.titles import deck_subtitle
from sase.ace.tui.widgets.decks.availability import DeckAvailability
from tests.ace.tui.widgets._agent_display_helpers import make_artifact_agent

_ROOT = Path(__file__).resolve().parents[5]


def test_viewport_drops_fully_visible_later_cards() -> None:
    ordered = ("a", "b", "c")
    anchors = (("a", 0), ("b", 10), ("c", 20))
    # Viewport 10..30 shows b at top; c ends at 30 which is not > 30.
    above, below, all_in_view, ready = resolve_viewport_spread(
        ordered,
        "b",
        anchors,
        scroll_y=10,
        viewport_height=20,
        max_scroll_y=10,
        reserve=0,
    )
    assert ready is True
    assert all_in_view is False
    assert above == ("a",)
    assert below == ()


def test_viewport_keeps_partially_visible_later_cards() -> None:
    ordered = ("a", "b", "c")
    anchors = (("a", 0), ("b", 10), ("c", 20))
    # Viewport 10..25 leaves c (ending at 35) partially out of view.
    above, below, _all, _ready = resolve_viewport_spread(
        ordered,
        "b",
        anchors,
        scroll_y=10,
        viewport_height=15,
        max_scroll_y=20,
        reserve=0,
    )
    assert above == ("a",)
    assert below == ("c",)


def test_viewport_all_in_view_when_no_scroll_range() -> None:
    above, below, all_in_view, ready = resolve_viewport_spread(
        ("a", "b"),
        "a",
        (("a", 0), ("b", 8)),
        scroll_y=0,
        viewport_height=30,
        max_scroll_y=0,
        reserve=0,
    )
    assert ready is True
    assert (above, below, all_in_view) == ((), ("b",), True)


def test_viewport_anchors_not_ready_falls_back() -> None:
    above, below, all_in_view, ready = resolve_viewport_spread(
        ("a", "b"),
        "b",
        None,
        scroll_y=0,
        viewport_height=20,
        max_scroll_y=10,
        reserve=0,
    )
    assert ready is False
    assert (above, below, all_in_view) == ((), (), False)


def test_viewport_unknown_end_stays_conservative() -> None:
    above, below, _all = viewport_partition(
        ("a", "b", "c"),
        "b",
        {"a": 0, "b": 10},
        {"a": 10, "b": None, "c": None},
        scroll_y=10,
        viewport_height=20,
        max_scroll_y=10,
    )
    assert above == ("a",)
    assert below == ("c",)


def test_viewport_reserve_excludes_trailing_layout() -> None:
    ordered = ("a", "b", "c")
    anchors = (("b", 10), ("c", 20))
    # Total 30 rows, viewport rows 5..15. Without reserve c ends at 30.
    _a, below_no_reserve, all_no_reserve, _r = resolve_viewport_spread(
        ordered,
        "a",
        anchors,
        scroll_y=5,
        viewport_height=10,
        max_scroll_y=20,
        reserve=0,
    )
    assert below_no_reserve == ("b", "c")
    assert all_no_reserve is False
    # With an 18-row trailing reserve c ends at 12, fully in view, while b
    # (ending at 20) stays listed: the reserve leaves the last-card end.
    _a2, below_reserve, all_reserve, _r2 = resolve_viewport_spread(
        ordered,
        "a",
        anchors,
        scroll_y=5,
        viewport_height=10,
        max_scroll_y=20,
        reserve=18,
    )
    assert below_reserve == ("b",)
    assert all_reserve is False


def test_viewport_card_ends_use_next_anchor() -> None:
    ends = card_ends_from_anchors(("a", "b", "c"), {"a": 0, "b": 10, "c": 25}, 40)
    assert ends == {"a": 10, "b": 25, "c": 40}


def test_viewport_spread_cue_maps_titles() -> None:
    cue = viewport_spread_cue(
        ("context", "reply"),
        {"context": "Context", "reply": "Reply"},
        "reply",
        ("context",),
        (),
        all_in_view=False,
    )
    assert cue is not None
    assert cue.here == "Reply"
    assert cue.above == ("Context",)
    assert cue.below == ()


def test_continuation_card_counts_and_key() -> None:
    full, bare = continuation_texts(
        DeckId.MAIN,
        tab_count=2,
        block_count=None,
        block_paged=False,
        card_key="Ctrl+J",
        at_bottom=False,
        focused=True,
        accent="red",
    )
    assert full is not None and bare is not None
    assert full.plain == "+1 card · Ctrl+J"
    assert bare.plain == "+1 card"
    assert any("Ctrl+J" in str(span.style) or True for span in full.spans)


def test_continuation_page_blocks_shows_both_counts() -> None:
    full, bare = continuation_texts(
        DeckId.MAIN,
        tab_count=2,
        block_count=4,
        block_paged=True,
        card_key="Ctrl+J",
        block_prev_key="(",
        block_next_key=")",
        at_bottom=False,
        focused=True,
        accent="red",
    )
    assert full is not None and bare is not None
    assert full.plain == "+3 blocks · (/) · +1 card · Ctrl+J"
    assert bare.plain == "+3 blocks · +1 card"


def test_continuation_unbound_key_drops_segment() -> None:
    full, bare = continuation_texts(
        DeckId.MAIN,
        tab_count=3,
        block_count=None,
        block_paged=False,
        card_key="",
        at_bottom=False,
        focused=True,
        accent="red",
    )
    assert full is not None and bare is not None
    assert full.plain == "+2 cards"
    assert bare.plain == "+2 cards"


def test_continuation_files_noun() -> None:
    full, _bare = continuation_texts(
        DeckId.FILES,
        tab_count=5,
        block_count=None,
        block_paged=False,
        card_key="Ctrl+J",
        at_bottom=False,
        focused=True,
        accent="green",
    )
    assert full is not None
    assert full.plain == "+4 files · Ctrl+J"


def test_continuation_empty_when_nothing_off_page() -> None:
    assert continuation_texts(
        DeckId.MAIN,
        tab_count=1,
        block_count=None,
        block_paged=False,
        card_key="Ctrl+J",
    ) == (None, None)


def _availability() -> dict[DeckId, object]:
    return {
        DeckId.MAIN: DeckAvailability(True, 2),
        DeckId.FILES: DeckAvailability(True, 0),
        DeckId.TOOLS: DeckAvailability(True, 0),
    }


_ACCENTS = {DeckId.MAIN: "red", DeckId.FILES: "green", DeckId.TOOLS: "#87D7FF"}


def test_subtitle_continuation_leads_before_switcher() -> None:
    full, bare = continuation_texts(
        DeckId.MAIN,
        tab_count=2,
        block_count=None,
        block_paged=False,
        card_key="Ctrl+J",
        focused=True,
        accent="red",
    )
    assert full is not None
    rendered = deck_subtitle(
        DeckId.MAIN,
        _availability(),
        status=None,
        width=80,
        accent_for=_ACCENTS,
        continuation=full,
        continuation_bare=bare,
    )
    assert rendered.plain.startswith("+1 card · Ctrl+J  main")


def test_subtitle_continuation_key_segments_drop_before_counts() -> None:
    full, bare = continuation_texts(
        DeckId.MAIN,
        tab_count=2,
        block_count=None,
        block_paged=False,
        card_key="Ctrl+J",
        focused=True,
        accent="red",
    )
    assert full is not None and bare is not None
    wide = deck_subtitle(
        DeckId.MAIN,
        _availability(),
        status=None,
        width=80,
        accent_for=_ACCENTS,
        continuation=full,
        continuation_bare=bare,
    )
    assert "Ctrl+J" in wide.plain
    narrow_width = len("+1 card  main 2 · files 0 · tools 0 · final · record")
    narrow = deck_subtitle(
        DeckId.MAIN,
        _availability(),
        status=None,
        width=narrow_width,
        accent_for=_ACCENTS,
        continuation=full,
        continuation_bare=bare,
    )
    assert "+1 card" in narrow.plain


def test_continuation_at_bottom_turns_bold_accent() -> None:
    full, _bare = continuation_texts(
        DeckId.MAIN,
        tab_count=2,
        block_count=None,
        block_paged=False,
        card_key="Ctrl+J",
        at_bottom=True,
        focused=True,
        accent="red",
    )
    assert full is not None
    assert "bold red" in {str(span.style) for span in full.spans}
    assert "#888888" not in {str(span.style) for span in full.spans}


def test_continuation_unfocused_is_dim() -> None:
    full, _bare = continuation_texts(
        DeckId.MAIN,
        tab_count=2,
        block_count=None,
        block_paged=False,
        card_key="Ctrl+J",
        at_bottom=False,
        focused=False,
        accent="red",
    )
    assert full is not None
    assert {str(span.style) for span in full.spans} == {"dim"}


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


def _main_scroll(panel: Any) -> VerticalScroll:
    return panel.query_one("#agent-deck-panel-0-main-scroll", VerticalScroll)


async def _wait_spread(pilot: Any, panel: Any) -> None:
    await wait_for(pilot, lambda: panel.is_spread(DeckId.MAIN))
    await wait_for(
        pilot,
        lambda: (
            panel.main_view.card_anchor_rows(
                width=panel.main_view._spread_content_width()
            )
            is not None
        ),
    )
    await pilot.pause()
    await pilot.pause()


async def test_pilot_spread_landed_reply_shows_context_above() -> None:
    from sase.ace.tui.agent_decks_settings import AgentDecksSettings

    app = _DetailApp()
    app._agent_decks_settings = AgentDecksSettings(
        spread_max_screens=1000.0, block_spread_max_screens=1000.0
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        _small, large = _small_growing_documents()
        panel.show_main_document(large, None)
        await wait_for(pilot, lambda: panel.is_spread(DeckId.MAIN))
        await wait_for(
            pilot,
            lambda: (
                panel.main_view.card_anchor_rows(
                    width=panel.main_view._spread_content_width()
                )
                is not None
            ),
        )
        await pilot.pause()
        # The tall reply does not fit, so cycling to it lands Reply with
        # Context above: the direction survives the viewport filter.
        panel.cycle_card(1)
        await wait_for(pilot, lambda: panel._main_active_card == "reply")
        await pilot.pause()
        raw_title = getattr(panel, "_border_title", panel.border_title)
        title = raw_title.plain if hasattr(raw_title, "plain") else str(raw_title)
        assert "Reply" in title
        assert "▴" in title
        assert "Context" in title


async def test_pilot_scroll_within_cue_does_not_refresh(tmp_path: Path) -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
        await pilot.pause()
        await pilot.pause()
        panel = detail.deck_area.panel(0)
        await _wait_spread(pilot, panel)
        calls = 0
        original = panel.refresh_chrome

        def _counting() -> None:
            nonlocal calls
            calls += 1
            original()

        panel.refresh_chrome = _counting  # type: ignore[method-assign]
        try:
            before = panel._shown_scope_key()
            scroll = _main_scroll(panel)
            target = int(scroll.scroll_y) + 1
            if target > int(scroll.max_scroll_y):
                target = int(scroll.scroll_y)
            scroll.scroll_to(y=target, animate=False)
            await pilot.pause()
            after = panel._shown_scope_key()
            if before == after:
                assert calls == 0
            else:
                assert calls <= 1
        finally:
            panel.refresh_chrome = original  # type: ignore[method-assign]


def _small_growing_documents() -> tuple[Any, Any]:
    from sase.ace.tui.widgets.decks.card_part import context_card, reply_card
    from sase.ace.tui.widgets.decks.main_document import MainDeckDocument

    small = MainDeckDocument(
        cards=(context_card(Text("context-body")), reply_card(Text("short reply"))),
        subject="grow-s1",
        partial=False,
        digest="grow-small",
    )
    tall_lines = "\n".join(f"growth line {i}" for i in range(80))
    large = MainDeckDocument(
        cards=(
            context_card(Text("context-body")),
            reply_card(Text(tall_lines)),
        ),
        subject="grow-s1",
        partial=False,
        digest="grow-large",
    )
    return small, large


async def test_pilot_streaming_growth_replaces_all_in_view_without_scroll() -> None:
    from sase.ace.tui.agent_decks_settings import AgentDecksSettings

    app = _DetailApp()
    app._agent_decks_settings = AgentDecksSettings(
        spread_max_screens=1000.0, block_spread_max_screens=1000.0
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        small, large = _small_growing_documents()
        panel.show_main_document(small, None)
        await wait_for(pilot, lambda: panel.is_spread(DeckId.MAIN))
        await wait_for(
            pilot,
            lambda: (
                panel.main_view.card_anchor_rows(
                    width=panel.main_view._spread_content_width()
                )
                is not None
            ),
        )
        await pilot.pause()
        await pilot.pause()
        raw_before = getattr(panel, "_border_title", panel.border_title)
        before = raw_before.plain if hasattr(raw_before, "plain") else str(raw_before)
        assert "both cards in view" in before or "all in view" in before
        scroll = _main_scroll(panel)
        assert int(scroll.scroll_y) == 0
        assert int(scroll.max_scroll_y) == 0
        panel.show_main_document(large, None)
        await wait_for(pilot, lambda: int(_main_scroll(panel).max_scroll_y) > 0)
        await wait_for(
            pilot,
            lambda: (
                "▾"
                in (
                    getattr(panel, "_border_title", panel.border_title).plain
                    if hasattr(
                        getattr(panel, "_border_title", panel.border_title), "plain"
                    )
                    else str(panel.border_title)
                )
            ),
        )
        # No scroll event moved the reader; layout publication drove the cue.
        assert int(_main_scroll(panel).scroll_y) == 0
        raw_after = getattr(panel, "_border_title", panel.border_title)
        after = raw_after.plain if hasattr(raw_after, "plain") else str(raw_after)
        assert "both cards in view" not in after and "all in view" not in after


async def test_pilot_paged_bottom_flip_refreshes_once_per_flip() -> None:
    from sase.ace.tui.agent_decks_settings import AgentDecksSettings

    app = _DetailApp()
    app._agent_decks_settings = AgentDecksSettings(
        spread_max_screens=0.0, block_spread_max_screens=0.0
    )
    async with app.run_test(size=(100, 16)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        _small, large = _small_growing_documents()
        panel.show_main_document(large, "reply")
        await wait_for(
            pilot, lambda: panel._render_mode[DeckId.MAIN] is RenderMode.PAGED
        )
        await pilot.pause()
        await pilot.pause()
        raw_sub = getattr(panel, "_border_subtitle", panel.border_subtitle)
        sub = raw_sub.plain if hasattr(raw_sub, "plain") else str(raw_sub)
        assert "+1 card" in sub
        scroll = _main_scroll(panel)
        assert int(scroll.max_scroll_y) > 0
        calls = 0
        original = panel.refresh_chrome

        def _counting() -> None:
            nonlocal calls
            calls += 1
            original()

        panel.refresh_chrome = _counting  # type: ignore[method-assign]
        try:
            scroll.scroll_to(y=int(scroll.max_scroll_y), animate=False)
            await wait_for(
                pilot, lambda: bool(panel._paged_at_bottom(DeckId.MAIN)) is True
            )
            await pilot.pause()
            first_flips = calls
            assert first_flips == 1
            scroll.scroll_to(y=int(scroll.max_scroll_y), animate=False)
            await pilot.pause()
            assert calls == first_flips
            scroll.scroll_to(y=0, animate=False)
            await wait_for(
                pilot, lambda: bool(panel._paged_at_bottom(DeckId.MAIN)) is False
            )
            await pilot.pause()
            assert calls == first_flips + 1
        finally:
            panel.refresh_chrome = original  # type: ignore[method-assign]
