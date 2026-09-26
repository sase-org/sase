"""Pilot block-spread and deck-spread navigation tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from sase.ace.testing import wait_for
from sase.ace.tui.agent_decks_settings import AgentDecksSettings
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.card_block import BlockMeta, CardBlock
from sase.ace.tui.widgets.decks.card_part import CardPart, context_card, reply_card
from sase.ace.tui.widgets.decks.main_document import MainDeckDocument
from sase.ace.tui.widgets.decks.model import DeckId, RenderMode

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
    from sase.ace.tui.widgets.prompt_panel._agent_display_content import (
        render_phase_divider,
    )

    header = render_phase_divider(
        f"AGENT ({block_id})",
        None,
        accent="#AF87FF",
        block_id=block_id,
    )
    return CardBlock(
        block_id,
        f"block {block_id}",
        header,
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


def _scroll(panel: Any) -> VerticalScroll:
    return panel.query_one(
        "#agent-deck-panel-0-main-scroll",
        VerticalScroll,
    )


async def test_block_spread_lands_on_newest_clamp() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        # Paged deck (deck=0) with block-spread (blocks=1000).
        _pin(app, deck=0, blocks=1000)
        panel = await _panel(app)
        panel.show_main_document(
            _document("s1", _reply_card(3), digest="spread-1"), "reply"
        )
        await wait_for(
            pilot, lambda: panel.block_mode_for_active_card() is RenderMode.SPREAD
        )
        view = panel.main_view
        assert view.active_block_id("reply") == "b2"
        card = panel._main_document.card("reply")
        assert card is not None
        await wait_for(pilot, lambda: view.spread_landing_target(card) is not None)
        target = view.spread_landing_target(card)
        assert target is not None
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == target)


async def test_block_spread_bracket_top_aligns() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=0, blocks=1000)
        panel = await _panel(app)
        panel.show_main_document(
            _document("s1", _reply_card(3, lines_per_block=10), digest="spread-2"),
            "reply",
        )
        await wait_for(
            pilot, lambda: panel.block_mode_for_active_card() is RenderMode.SPREAD
        )
        view = panel.main_view
        await wait_for(pilot, lambda: view.block_header_row("b2") is not None)
        card = panel._main_document.card("reply")
        assert card is not None
        await wait_for(pilot, lambda: view.spread_landing_target(card) is not None)
        target = view.spread_landing_target(card)
        assert target is not None
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == target)
        assert panel.cycle_block(-1) is True
        assert view.active_block_id("reply") == "b1"
        header = view.block_header_row("b1")
        assert header is not None
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == header)


async def test_deck_spread_sticky_reply_landing() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        # Small two-card document fits: deck-spread. Blocks fit too.
        _pin(app, deck=1.5, blocks=1000)
        panel = await _panel(app)
        panel.show_main_document(
            _document("s1", _reply_card(3), digest="spread-3"), "reply"
        )
        await wait_for(
            pilot, lambda: panel._render_mode[DeckId.MAIN] is RenderMode.SPREAD
        )
        view = panel.main_view
        card = panel._main_document.card("reply")
        assert card is not None
        await wait_for(pilot, lambda: view.spread_landing_target(card) is not None)
        target = view.spread_landing_target(card)
        assert target is not None
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == target)
        assert view.active_block_id("reply") == "b2"


async def test_deck_spread_bracket_from_above_first_header() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=10, blocks=1000)
        panel = await _panel(app)
        panel.show_main_document(
            _document("s1", _reply_card(3, lines_per_block=10), digest="spread-4"),
            "reply",
        )
        await wait_for(
            pilot, lambda: panel._render_mode[DeckId.MAIN] is RenderMode.SPREAD
        )
        view = panel.main_view
        await wait_for(pilot, lambda: view.block_header_row("b0") is not None)
        card = panel._main_document.card("reply")
        assert card is not None
        await wait_for(pilot, lambda: view.spread_landing_target(card) is not None)
        landing = view.spread_landing_target(card)
        assert landing is not None
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == landing)
        # Park above the first block header (tall deck-spread, scroll 0 is
        # not the real bottom): ] reaches oldest, [ newest.
        _scroll(panel).scroll_to(y=0, animate=False)
        await pilot.pause()
        await pilot.pause()
        assert panel.cycle_block(1) is True
        assert view.active_block_id("reply") == "b0"
        _scroll(panel).scroll_to(y=0, animate=False)
        await pilot.pause()
        await pilot.pause()
        assert panel.cycle_block(-1) is True
        assert view.active_block_id("reply") == "b2"


async def test_scroll_derived_cursor_and_streaming_stays() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=0, blocks=1000)
        panel = await _panel(app)
        panel.show_main_document(
            _document("s1", _reply_card(3, lines_per_block=10), digest="spread-5"),
            "reply",
        )
        await wait_for(
            pilot, lambda: panel.block_mode_for_active_card() is RenderMode.SPREAD
        )
        view = panel.main_view
        await wait_for(pilot, lambda: view.block_header_row("b0") is not None)
        card = panel._main_document.card("reply")
        assert card is not None
        await wait_for(pilot, lambda: view.spread_landing_target(card) is not None)
        landing = view.spread_landing_target(card)
        assert landing is not None
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == landing)
        header0 = view.block_header_row("b0")
        assert header0 is not None
        _scroll(panel).scroll_to(y=header0, animate=False)
        await wait_for(pilot, lambda: view.active_block_id("reply") == "b0")
        cursor = view._block_cursors["reply"]
        assert cursor.following is False
        # Streaming growth does not move scroll_y, so a parked reader
        # stays put with an arrival announced.
        panel.show_main_document(
            _document(
                "s1", _reply_card(4, lines_per_block=10), digest="spread-new-shell"
            ),
            "reply",
        )
        await pilot.pause()
        assert view.active_block_id("reply") == "b0"
        assert view._block_cursors["reply"].following is False
        assert view.arrived_block_ids("reply") == ("b3",)


async def test_block_spread_to_paged_keeps_reader_block() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=0, blocks=1000)
        panel = await _panel(app)
        panel.show_main_document(
            _document("s1", _reply_card(3), digest="spread-6"), "reply"
        )
        await wait_for(
            pilot, lambda: panel.block_mode_for_active_card() is RenderMode.SPREAD
        )
        view = panel.main_view
        await wait_for(pilot, lambda: view.block_header_row("b2") is not None)
        card = panel._main_document.card("reply")
        assert card is not None
        await wait_for(pilot, lambda: view.spread_landing_target(card) is not None)
        landing = view.spread_landing_target(card)
        assert landing is not None
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == landing)
        assert panel.cycle_block(-1) is True
        assert panel.main_view.active_block_id("reply") == "b1"
        # Flip to always-paged blocks: the reader's block survives.
        _pin(app, deck=0, blocks=0)
        panel._refresh_main_mode_for_shown()
        await pilot.pause()
        assert panel.block_mode_for_active_card() is RenderMode.PAGED
        assert panel.main_view.active_block_id("reply") == "b1"


async def test_deck_spread_to_paged_into_block_page() -> None:
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=1.5, blocks=0)
        panel = await _panel(app)
        panel.show_main_document(
            _document("s1", _reply_card(3), digest="spread-7"), "reply"
        )
        await wait_for(
            pilot, lambda: panel._render_mode[DeckId.MAIN] is RenderMode.SPREAD
        )
        subject = panel._main_document.subject
        big_reply = _reply_card(3, lines_per_block=100)
        grown = MainDeckDocument(
            cards=(context_card(Text("ctx")), big_reply),
            subject=subject,
            partial=False,
            digest="grown-digest",
        )
        panel.show_main_document(grown, preferred_card=None)
        await pilot.pause()
        assert panel._render_mode[DeckId.MAIN] is RenderMode.PAGED
        assert panel.main_view.active_card_id in ("context", "reply")
        if panel.main_view.active_card_id == "reply":
            assert panel.main_view.active_block_id("reply") == "b2"
