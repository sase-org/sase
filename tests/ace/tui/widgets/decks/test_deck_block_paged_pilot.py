"""Pilot block-paged projection tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.text import Text
from textual.app import App, ComposeResult

from sase.ace.testing import wait_for
from sase.ace.tui.agent_decks_settings import AgentDecksSettings
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.card_block import BlockMeta, CardBlock
from sase.ace.tui.widgets.decks.card_part import CardPart, context_card, reply_card
from sase.ace.tui.widgets.decks.main_document import MainDeckDocument
from sase.ace.tui.widgets.decks.model import DeckId, RenderMode
from sase.ace.tui.widgets.decks.search_corpus import deck_search_corpus
from sase.ace.tui.widgets.renderable_text import renderable_to_text

_ROOT = Path(__file__).resolve().parents[5]


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


def _meta(label: str) -> BlockMeta:
    return BlockMeta(
        number="0",
        label=label,
        glyph="",
        accent="#AF87FF",
        status_bucket="Done",
        kind="agent",
    )


def _block(block_id: str, *lines: str) -> CardBlock:
    return CardBlock(
        block_id,
        f"block {block_id}",
        Text("\n".join(lines)),
        meta=_meta(block_id),
    )


def _reply_card(block_count: int, *, lines_per_block: int = 3) -> CardPart:
    blocks = [
        _block(
            f"b{i}",
            *(f"block-{i}-line-{j}" for j in range(lines_per_block)),
        )
        for i in range(block_count)
    ]
    return reply_card(Text("TRACEBACK-draw"), *blocks)


def _document(
    subject: object,
    reply: CardPart,
    *,
    digest: str,
    partial: bool = False,
) -> MainDeckDocument:
    return MainDeckDocument(
        cards=(context_card(Text("context-body")), reply),
        subject=subject,
        partial=partial,
        digest=digest,
    )


def _pin(app: Any, *, deck: float = 0, blocks: float = 0) -> None:
    app._agent_decks_settings = AgentDecksSettings(
        spread_max_screens=deck, block_spread_max_screens=blocks
    )


async def _panel(app: _DetailApp) -> Any:
    detail = app.query_one("#agent-detail-panel", AgentDetail)
    return detail.deck_area.panel(0)


async def test_block_paged_lands_on_newest() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app)
        panel = await _panel(app)
        active = panel.show_main_document(
            _document("s1", _reply_card(3), digest="d1"), "reply"
        )
        await pilot.pause()
        assert active == "reply"
        view = panel.main_view
        assert view.active_block_id("reply") == "b2"
        assert panel.block_mode_for_active_card() is RenderMode.PAGED
        assert view._last_render_key == ("d1", "reply", False, "paged", "b2")
        assert panel.card_blocks_navigable is True
        # Newest page carries the preamble plus the newest block only.
        card = panel._main_document.card("reply")
        assert card is not None
        projected = view._project_block_content(
            panel._main_document, card, RenderMode.PAGED
        )
        assert projected is not None
        text = renderable_to_text(projected[0]) or ""
        assert "TRACEBACK-draw" in text
        assert "block-2-line-0" in text
        assert "block-0-line-0" not in text


async def test_cycle_block_reaches_previous_with_wrap() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app)
        panel = await _panel(app)
        panel.show_main_document(_document("s1", _reply_card(3), digest="d1"), "reply")
        await pilot.pause()
        view = panel.main_view
        assert panel.cycle_block(-1) is True
        assert view.active_block_id("reply") == "b1"
        cursor = view._block_cursors["reply"]
        assert cursor.following is False
        assert panel.cycle_block(-1) is True
        assert view.active_block_id("reply") == "b0"
        # Wrapping from the oldest block lands back on the newest.
        assert panel.cycle_block(-1) is True
        assert view.active_block_id("reply") == "b2"
        assert view._block_cursors["reply"].following is True
        assert panel.cycle_block(1) is True
        assert view.active_block_id("reply") == "b0"


async def test_select_block_targets_oldest() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app)
        panel = await _panel(app)
        panel.show_main_document(_document("s1", _reply_card(3), digest="d1"), "reply")
        await pilot.pause()
        assert panel.select_block("b0") is True
        assert panel.main_view.active_block_id("reply") == "b0"
        assert panel.select_block("b9") is False
        assert panel.main_view.active_block_id("reply") == "b0"


async def test_streaming_new_shell_following_advances() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app)
        panel = await _panel(app)
        panel.show_main_document(_document("s1", _reply_card(3), digest="d1"), "reply")
        await pilot.pause()
        view = panel.main_view
        assert view.active_block_id("reply") == "b2"
        panel.show_main_document(_document("s1", _reply_card(4), digest="d2"), "reply")
        await pilot.pause()
        assert view.active_block_id("reply") == "b3"
        assert view._block_cursors["reply"].following is True
        assert view.arrived_block_ids("reply") == ()


async def test_streaming_new_shell_not_following_stays() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app)
        panel = await _panel(app)
        panel.show_main_document(_document("s1", _reply_card(3), digest="d1"), "reply")
        await pilot.pause()
        assert panel.cycle_block(-1) is True
        assert panel.main_view.active_block_id("reply") == "b1"
        panel.show_main_document(_document("s1", _reply_card(4), digest="d2"), "reply")
        await pilot.pause()
        view = panel.main_view
        # Parked on history: never yanked out, arrival announced.
        assert view.active_block_id("reply") == "b1"
        assert view._block_cursors["reply"].following is False
        assert view.arrived_block_ids("reply") == ("b3",)


async def test_subject_reset_on_new_subject() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app)
        panel = await _panel(app)
        panel.show_main_document(_document("s1", _reply_card(3), digest="d1"), "reply")
        await pilot.pause()
        assert panel.cycle_block(-1) is True
        panel.show_main_document(_document("s2", _reply_card(3), digest="d3"), "reply")
        await pilot.pause()
        view = panel.main_view
        assert view.active_block_id("reply") == "b2"
        assert view._block_cursors["reply"].following is True


async def test_partial_paint_never_touches_cursors() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app)
        panel = await _panel(app)
        panel.show_main_document(_document("s1", _reply_card(3), digest="d1"), "reply")
        await pilot.pause()
        assert panel.cycle_block(-1) is True
        before = panel.main_view._block_cursors["reply"]
        panel.show_main_document(
            _document("s1", _reply_card(3), digest="d1p", partial=True),
            "reply",
        )
        await pilot.pause()
        view = panel.main_view
        assert view._block_cursors["reply"] == before
        assert view.active_block_id("reply") == "b1"
        assert panel.card_blocks_navigable is False


async def test_split_panels_keep_independent_cursors() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app)
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        left = detail.deck_area.panel(0)
        right = detail.deck_area.panel(1)
        left.show_main_document(_document("s1", _reply_card(3), digest="d1"), "reply")
        right.show_main_document(_document("s1", _reply_card(3), digest="d1"), "reply")
        await pilot.pause()
        assert left.cycle_block(-1) is True
        assert left.main_view.active_block_id("reply") == "b1"
        assert right.main_view.active_block_id("reply") == "b2"


async def test_block_spread_renders_whole_card() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, blocks=1000)
        panel = await _panel(app)
        panel.show_main_document(_document("s1", _reply_card(3), digest="d1"), "reply")
        await pilot.pause()
        view = panel.main_view
        assert panel.block_mode_for_active_card() is RenderMode.SPREAD
        assert view._last_render_key == ("d1", "reply", False, "paged", "spread")
        # Cursors still reconcile so a later flip to paged lands ready.
        assert view.active_block_id("reply") == "b2"


async def test_zero_block_screens_always_pages() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, blocks=0)
        panel = await _panel(app)
        panel.show_main_document(
            _document("s1", _reply_card(2, lines_per_block=1), digest="d1"),
            "reply",
        )
        await pilot.pause()
        assert panel.block_mode_for_active_card() is RenderMode.PAGED
        assert panel.main_view.active_block_id("reply") == "b1"


async def test_block_mode_hysteresis_band() -> None:
    from sase.ace.tui.widgets.decks.render_mode import SPREAD_HYSTERESIS

    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        panel = await _panel(app)
        console = Console(width=80)
        panel._spread_viewport = lambda deck: (20, 80)  # type: ignore[method-assign]
        panel._spread_console = lambda: (console, console.options)  # type: ignore[method-assign]
        _pin(app, blocks=1.0)
        budget = 20.0
        # 10 rows fits the 20-row budget: block-spread.
        card = _reply_card(2, lines_per_block=5)
        assert (
            panel._decide_block_mode(_document("s1", card, digest="h0"), card)
            is RenderMode.SPREAD
        )
        # 21 rows crosses the budget but stays inside the +10% band.
        assert budget * (1 + SPREAD_HYSTERESIS) >= 21
        card = _reply_card(2, lines_per_block=10)
        assert (
            panel._decide_block_mode(_document("s1", card, digest="h1"), card)
            is RenderMode.SPREAD
        )
        # 30 rows leaves the band: block-paged.
        card = _reply_card(2, lines_per_block=15)
        assert (
            panel._decide_block_mode(_document("s1", card, digest="h2"), card)
            is RenderMode.PAGED
        )
        # 19 rows is back under budget but inside the -10% band.
        assert budget * (1 - SPREAD_HYSTERESIS) < 19
        small = CardPart(
            "reply",
            "Reply",
            _block("b0", *("x" for _ in range(9))),
            _block("b1", *("y" for _ in range(10))),
        )
        assert (
            panel._decide_block_mode(_document("s1", small, digest="h3"), small)
            is RenderMode.PAGED
        )


async def test_hidden_blocks_stay_searchable() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app)
        panel = await _panel(app)
        panel.show_main_document(_document("s1", _reply_card(3), digest="d1"), "reply")
        await pilot.pause()
        corpus = deck_search_corpus(panel)
        assert "block-0-line-0" in corpus
        assert "block-2-line-2" in corpus
        # Projection never mutates the card: E-class readers stay card-wide.
        card = panel._main_document.card("reply")
        assert card is not None and len(card.blocks) == 3


async def test_cycle_focused_card_block_sets_preferred() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app)
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        panel.show_main_document(_document("s1", _reply_card(3), digest="d1"), "reply")
        await pilot.pause()
        assert detail.cycle_focused_card_block(-1) is True
        assert panel.main_view.active_block_id("reply") == "b1"
        assert (
            detail.deck_area.state.panels[panel.panel_index].preferred_card == "reply"
        )
        assert detail.select_focused_card_block("b0") is True
        assert panel.main_view.active_block_id("reply") == "b0"


async def test_block_spread_to_paged_keeps_scrollbar_in_sync() -> None:
    """A block-spread to block-paged flip must not strand the scrollbar.

    Textual only pushes ``scroll_y`` to ``ScrollBar.position`` while the bar
    is shown, and the layout shrink that hides the bar clamps ``scroll_y``
    first -- so without an explicit sync the thumb keeps the old spread
    offset while the scroller sits at 0, until the next explicit scroll.
    """
    from textual.containers import VerticalScroll

    def _scroller(panel: Any) -> VerticalScroll:
        return panel.query_one(
            f"#agent-deck-panel-{panel._panel_index}-main-scroll",
            VerticalScroll,
        )

    app = _DetailApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        left = detail.deck_area.panel(0)
        right = detail.deck_area.panel(1)
        tall = _reply_card(12, lines_per_block=10)
        _pin(app, blocks=1000)
        left.show_main_document(_document("s1", tall, digest="d1"), "reply")
        right.show_main_document(_document("s1", tall, digest="d1"), "reply")
        await pilot.pause(delay=0.3)
        await pilot.pause()
        assert left.block_mode_for_active_card() is RenderMode.SPREAD
        # Park the narrow split's left panel at the bottom of the tall
        # spread content, arming the stale-thumb condition.
        parked = _scroller(left)
        assert parked.max_scroll_y > 0
        parked.scroll_to(y=parked.max_scroll_y, animate=False, immediate=True)
        await pilot.pause(delay=0.2)
        await pilot.pause()
        parked = _scroller(left)
        assert parked.scroll_y == parked.max_scroll_y
        assert parked.vertical_scrollbar.position == parked.scroll_y
        # Flip both panels to block-paged through the same redecision path
        # a measured first paint takes after an unmeasured spread landing.
        _pin(app, blocks=0)
        left._refresh_main_mode_for_shown()
        right._refresh_main_mode_for_shown()

        def _paged_and_synced() -> bool:
            if not (
                left.block_mode_for_active_card() is RenderMode.PAGED
                and right.block_mode_for_active_card() is RenderMode.PAGED
            ):
                return False
            return all(
                float(_scroller(panel).vertical_scrollbar.position)
                == float(_scroller(panel).scroll_y)
                for panel in (left, right)
            )

        await wait_for(pilot, _paged_and_synced)
        for panel in (left, right):
            scroller = _scroller(panel)
            assert panel.block_mode_for_active_card() is RenderMode.PAGED
            assert scroller.scroll_y == 0
            assert scroller.vertical_scrollbar.position == scroller.scroll_y
        # The reading anchor and [ / ] navigation survive the flip, and the
        # split keeps independent cursors.
        assert left.main_view.active_block_id("reply") == "b11"
        assert left.cycle_block(-1) is True
        assert left.main_view.active_block_id("reply") == "b10"
        assert right.main_view.active_block_id("reply") == "b11"
        assert left.cycle_block(1) is True
        assert left.main_view.active_block_id("reply") == "b11"
