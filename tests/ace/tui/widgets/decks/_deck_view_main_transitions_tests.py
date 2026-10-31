from __future__ import annotations

from typing import Any

import pytest
from textual.containers import VerticalScroll

from sase.ace.testing import wait_for
from sase.ace.tui.widgets.decks.model import DeckId, DeckView, RenderMode
from tests.ace.tui.widgets.decks._deck_view_main_support import (
    MainDetailApp,
    get_panel,
    make_document,
    make_reply_card,
    pin_settings,
    settle_view,
)


def _scroll(panel: Any) -> VerticalScroll:
    return panel.query_one(
        "#agent-deck-panel-0-main-scroll",
        VerticalScroll,
    )


def _following(panel: Any) -> bool | None:
    try:
        cursor = panel.main_view._block_cursors.get("reply")
    except Exception:
        return None
    if cursor is None:
        return None
    return bool(getattr(cursor, "following", False))


async def _anchor_on_b1(pilot: Any, panel: Any, start: DeckView) -> None:
    """Park the reader on block b1 for the starting layout."""
    view = panel.main_view
    if start is DeckView.PAGE_BLOCKS:
        assert panel.cycle_block(-1) is True
        await wait_for(pilot, lambda: view.active_block_id("reply") == "b1")
    else:
        await wait_for(pilot, lambda: view.block_header_row("b1") is not None)
        assert view.scroll_to_block("b1") is True
        await wait_for(pilot, lambda: view.active_block_id("reply") == "b1")
        await pilot.pause()
        await pilot.pause()


async def _expected_row(pilot: Any, panel: Any) -> int:
    """Return b1's published header row (0 when anchors stay unpublished)."""
    await pilot.pause()
    await pilot.pause()
    header = panel.main_view.block_header_row("b1")
    return int(header) if header is not None else 0


# start layout -> (deck pin, block pin, effective layout)
_STARTS: dict[str, dict[str, Any]] = {
    "spread": {"deck": 1000.0, "blocks": 1000.0, "layout": DeckView.SPREAD},
    "page_cards": {"deck": 0.0, "blocks": 1000.0, "layout": DeckView.PAGE_CARDS},
    "page_blocks": {"deck": 0.0, "blocks": 0.0, "layout": DeckView.PAGE_BLOCKS},
}

_TRANSITIONS: tuple[tuple[str, DeckView], ...] = (
    ("spread", DeckView.PAGE_CARDS),
    ("spread", DeckView.PAGE_BLOCKS),
    ("page_cards", DeckView.SPREAD),
    ("page_cards", DeckView.PAGE_BLOCKS),
    ("page_blocks", DeckView.SPREAD),
    ("page_blocks", DeckView.PAGE_CARDS),
)


@pytest.mark.parametrize(("start", "target"), _TRANSITIONS)
async def test_view_change_keeps_block_and_offset(start: str, target: DeckView) -> None:
    """Every ordered layout transition keeps card, block, and offset."""
    setup = _STARTS[start]
    app = MainDetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pin_settings(app, deck=setup["deck"], blocks=setup["blocks"])
        panel = await get_panel(app)
        digest = f"view-keep-{start}-{target.value}"
        panel.show_main_document(
            make_document("s1", make_reply_card(3), digest=digest), "reply"
        )
        await settle_view(pilot, panel, setup["layout"])
        await _anchor_on_b1(pilot, panel, setup["layout"])
        before = _following(panel)
        assert int(_scroll(panel).scroll_y) > 0 or start == "page_blocks"

        panel.set_view_policy(DeckId.MAIN, target)
        await settle_view(pilot, panel, target)
        view = panel.main_view
        assert view.active_block_id("reply") == "b1"
        expected = await _expected_row(pilot, panel)
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == expected)
        assert _following(panel) == before
        assert panel.view_policy(DeckId.MAIN) is target


async def test_view_change_keeps_nonzero_offset() -> None:
    """A mid-block reading offset survives both directions of a change."""
    app = MainDetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pin_settings(app, deck=0, blocks=1000)
        panel = await get_panel(app)
        panel.show_main_document(
            make_document(
                "s1", make_reply_card(3, lines_per_block=30), digest="view-offset"
            ),
            "reply",
        )
        await settle_view(pilot, panel, DeckView.PAGE_CARDS)
        view = panel.main_view
        await wait_for(pilot, lambda: view.block_header_row("b1") is not None)
        assert view.scroll_to_block("b1") is True
        await wait_for(pilot, lambda: view.active_block_id("reply") == "b1")
        header = view.block_header_row("b1")
        assert header is not None and header > 0
        _scroll(panel).scroll_to(y=header + 4, animate=False)
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == header + 4)
        assert view.active_block_id("reply") == "b1"

        panel.set_view_policy(DeckId.MAIN, DeckView.SPREAD)
        await settle_view(pilot, panel, DeckView.SPREAD)
        await wait_for(pilot, lambda: view.block_header_row("b1") is not None)
        spread_row = view.block_header_row("b1")
        assert spread_row is not None
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == spread_row + 4)
        assert view.active_block_id("reply") == "b1"

        panel.set_view_policy(DeckId.MAIN, DeckView.PAGE_CARDS)
        await settle_view(pilot, panel, DeckView.PAGE_CARDS)
        await wait_for(pilot, lambda: view.block_header_row("b1") is not None)
        back_row = view.block_header_row("b1")
        assert back_row is not None
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == back_row + 4)
        assert view.active_block_id("reply") == "b1"


async def test_view_change_keeps_bottom_pin() -> None:
    """A pinned follower stays pinned across a view change."""
    app = MainDetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pin_settings(app, deck=0, blocks=0)
        panel = await get_panel(app)
        panel.show_main_document(
            make_document("s1", make_reply_card(3), digest="view-pin"), "reply"
        )
        await settle_view(pilot, panel, DeckView.PAGE_BLOCKS)
        panel.main_view.pin_to_bottom()
        await pilot.pause()
        assert bool(panel.main_view.is_pinned_to_bottom) is True

        panel.set_view_policy(DeckId.MAIN, DeckView.PAGE_CARDS)
        await settle_view(pilot, panel, DeckView.PAGE_CARDS)
        assert bool(panel.main_view.is_pinned_to_bottom) is True

        panel.set_view_policy(DeckId.MAIN, DeckView.SPREAD)
        await settle_view(pilot, panel, DeckView.SPREAD)
        assert bool(panel.main_view.is_pinned_to_bottom) is True


async def test_enter_page_blocks_shows_anchor_not_newest() -> None:
    """Entering page blocks from spread shows the scroll-derived block."""
    app = MainDetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pin_settings(app, deck=1000, blocks=1000)
        panel = await get_panel(app)
        panel.show_main_document(
            make_document("s1", make_reply_card(3), digest="view-anchor"), "reply"
        )
        await settle_view(pilot, panel, DeckView.SPREAD)
        view = panel.main_view
        await wait_for(pilot, lambda: view.block_header_row("b0") is not None)
        assert view.scroll_to_block("b0") is True
        await wait_for(pilot, lambda: view.active_block_id("reply") == "b0")

        panel.set_view_policy(DeckId.MAIN, DeckView.PAGE_BLOCKS)
        await settle_view(pilot, panel, DeckView.PAGE_BLOCKS)
        assert view.active_block_id("reply") == "b0"


async def test_rapid_view_changes_end_on_first_anchor() -> None:
    """Rapid P-P-P reuses the pending anchor and lands on its block."""
    app = MainDetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pin_settings(app, deck=1000, blocks=1000)
        panel = await get_panel(app)
        panel.show_main_document(
            make_document("s1", make_reply_card(3), digest="view-rapid"), "reply"
        )
        await settle_view(pilot, panel, DeckView.SPREAD)
        view = panel.main_view
        await wait_for(pilot, lambda: view.block_header_row("b1") is not None)
        assert view.scroll_to_block("b1") is True
        await wait_for(pilot, lambda: view.active_block_id("reply") == "b1")
        await pilot.pause()
        await pilot.pause()

        # Three synchronous changes: no paint runs between them, so every
        # change after the first must reuse the pending anchor.
        panel.set_view_policy(DeckId.MAIN, DeckView.PAGE_CARDS)
        panel.set_view_policy(DeckId.MAIN, DeckView.SPREAD)
        panel.set_view_policy(DeckId.MAIN, DeckView.PAGE_BLOCKS)
        await settle_view(pilot, panel, DeckView.PAGE_BLOCKS)
        assert view.active_block_id("reply") == "b1"
        expected = await _expected_row(pilot, panel)
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == expected)
        assert _following(panel) is False


async def test_partial_documents_store_without_applying() -> None:
    """Partial documents store the policy; the next full paint applies it."""
    app = MainDetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pin_settings(app, deck=0, blocks=1000)
        panel = await get_panel(app)
        panel.show_main_document(
            make_document("s1", make_reply_card(3), digest="view-partial"), "reply"
        )
        await settle_view(pilot, panel, DeckView.PAGE_CARDS)

        panel.show_main_document(
            make_document(
                "s1", make_reply_card(3), digest="view-partial-hdr", partial=True
            ),
            "reply",
        )
        await pilot.pause()
        panel.set_view_policy(DeckId.MAIN, DeckView.PAGE_BLOCKS)
        await pilot.pause()
        assert panel.view_policy(DeckId.MAIN) is DeckView.PAGE_BLOCKS

        panel.show_main_document(
            make_document("s1", make_reply_card(3), digest="view-partial-full"), "reply"
        )
        await settle_view(pilot, panel, DeckView.PAGE_BLOCKS)
        assert panel._render_mode[DeckId.MAIN] is RenderMode.PAGED
        assert panel.block_mode_for_active_card() is RenderMode.PAGED
