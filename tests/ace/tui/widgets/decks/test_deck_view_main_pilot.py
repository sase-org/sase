"""Pilot Main deck-view policy tests: transitions keep the reader's place."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from sase.ace.testing import wait_for
from sase.ace.tui.agent_decks_settings import AgentDecksSettings
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.card_block import BlockMeta, CardBlock
from sase.ace.tui.widgets.decks.card_part import CardPart, context_card, reply_card
from sase.ace.tui.widgets.decks.main_document import MainDeckDocument
from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout, DeckView, RenderMode

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


def _reply_card(block_count: int, *, lines_per_block: int = 12) -> CardPart:
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


def _following(panel: Any) -> bool | None:
    try:
        cursor = panel.main_view._block_cursors.get("reply")
    except Exception:
        return None
    if cursor is None:
        return None
    return bool(getattr(cursor, "following", False))


async def _settle(pilot: Any, panel: Any, layout: DeckView) -> None:
    await wait_for(pilot, lambda: panel.effective_layout(DeckId.MAIN) is layout)
    # Deferred Main bodies apply off the pump: wait until this generation's
    # body has been applied or dropped before asserting block/offset/pin.
    await wait_for(
        pilot,
        lambda: (
            int(getattr(panel, "_main_view_applied_generation", 0))
            >= int(getattr(panel, "_view_generation", 0))
        ),
    )
    try:
        view = panel.main_view
        await wait_for(
            pilot,
            lambda: (
                int(getattr(view, "_section_anchor_generation", -1))
                == int(getattr(view, "_section_generation", 0))
            ),
        )
    except Exception:
        pass
    await pilot.pause()
    await pilot.pause()


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
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=setup["deck"], blocks=setup["blocks"])
        panel = await _panel(app)
        digest = f"view-keep-{start}-{target.value}"
        panel.show_main_document(
            _document("s1", _reply_card(3), digest=digest), "reply"
        )
        await _settle(pilot, panel, setup["layout"])
        await _anchor_on_b1(pilot, panel, setup["layout"])
        before = _following(panel)
        assert int(_scroll(panel).scroll_y) > 0 or start == "page_blocks"

        panel.set_view_policy(DeckId.MAIN, target)
        await _settle(pilot, panel, target)
        view = panel.main_view
        assert view.active_block_id("reply") == "b1"
        expected = await _expected_row(pilot, panel)
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == expected)
        assert _following(panel) == before
        assert panel.view_policy(DeckId.MAIN) is target


async def test_view_change_keeps_nonzero_offset() -> None:
    """A mid-block reading offset survives both directions of a change."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=0, blocks=1000)
        panel = await _panel(app)
        panel.show_main_document(
            _document("s1", _reply_card(3, lines_per_block=30), digest="view-offset"),
            "reply",
        )
        await _settle(pilot, panel, DeckView.PAGE_CARDS)
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
        await _settle(pilot, panel, DeckView.SPREAD)
        await wait_for(pilot, lambda: view.block_header_row("b1") is not None)
        spread_row = view.block_header_row("b1")
        assert spread_row is not None
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == spread_row + 4)
        assert view.active_block_id("reply") == "b1"

        panel.set_view_policy(DeckId.MAIN, DeckView.PAGE_CARDS)
        await _settle(pilot, panel, DeckView.PAGE_CARDS)
        await wait_for(pilot, lambda: view.block_header_row("b1") is not None)
        back_row = view.block_header_row("b1")
        assert back_row is not None
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == back_row + 4)
        assert view.active_block_id("reply") == "b1"


async def test_view_change_keeps_bottom_pin() -> None:
    """A pinned follower stays pinned across a view change."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=0, blocks=0)
        panel = await _panel(app)
        panel.show_main_document(
            _document("s1", _reply_card(3), digest="view-pin"), "reply"
        )
        await _settle(pilot, panel, DeckView.PAGE_BLOCKS)
        panel.main_view.pin_to_bottom()
        await pilot.pause()
        assert bool(panel.main_view.is_pinned_to_bottom) is True

        panel.set_view_policy(DeckId.MAIN, DeckView.PAGE_CARDS)
        await _settle(pilot, panel, DeckView.PAGE_CARDS)
        assert bool(panel.main_view.is_pinned_to_bottom) is True

        panel.set_view_policy(DeckId.MAIN, DeckView.SPREAD)
        await _settle(pilot, panel, DeckView.SPREAD)
        assert bool(panel.main_view.is_pinned_to_bottom) is True


async def test_enter_page_blocks_shows_anchor_not_newest() -> None:
    """Entering page blocks from spread shows the scroll-derived block."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=1000, blocks=1000)
        panel = await _panel(app)
        panel.show_main_document(
            _document("s1", _reply_card(3), digest="view-anchor"), "reply"
        )
        await _settle(pilot, panel, DeckView.SPREAD)
        view = panel.main_view
        await wait_for(pilot, lambda: view.block_header_row("b0") is not None)
        assert view.scroll_to_block("b0") is True
        await wait_for(pilot, lambda: view.active_block_id("reply") == "b0")

        panel.set_view_policy(DeckId.MAIN, DeckView.PAGE_BLOCKS)
        await _settle(pilot, panel, DeckView.PAGE_BLOCKS)
        assert view.active_block_id("reply") == "b0"


async def test_fixed_policy_survives_navigation() -> None:
    """A fixed policy survives subjects, cards, deck switches, split, zoom."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=0, blocks=1000)
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        area = detail.deck_area
        panel = area.panel(0)
        panel.show_main_document(
            _document("s1", _reply_card(3), digest="view-survive"), "reply"
        )
        await _settle(pilot, panel, DeckView.PAGE_CARDS)
        area.set_panel_view(0, DeckId.MAIN, DeckView.PAGE_CARDS)
        assert panel.view_policy(DeckId.MAIN) is DeckView.PAGE_CARDS
        assert area.state.panels[0].views.main is DeckView.PAGE_CARDS

        # j/k: a new subject lands with today's rules under the fixed policy.
        panel.show_main_document(
            _document("s2", _reply_card(3), digest="view-survive-2"), "reply"
        )
        await _settle(pilot, panel, DeckView.PAGE_CARDS)
        assert panel.view_policy(DeckId.MAIN) is DeckView.PAGE_CARDS
        assert panel._render_mode[DeckId.MAIN] is RenderMode.PAGED
        assert panel.block_mode_for_active_card() is RenderMode.SPREAD

        # Ctrl+J/K: a preferred-card change keeps the policy.
        area.set_preferred_card(0, "context")
        await pilot.pause()
        assert panel.view_policy(DeckId.MAIN) is DeckView.PAGE_CARDS
        area.set_preferred_card(0, "reply")
        await pilot.pause()

        # Deck switch away and back keeps the policy and the forced modes.
        panel.set_deck(DeckId.FILES)
        await pilot.pause()
        panel.set_deck(DeckId.MAIN)
        await _settle(pilot, panel, DeckView.PAGE_CARDS)
        assert panel.view_policy(DeckId.MAIN) is DeckView.PAGE_CARDS
        assert panel._render_mode[DeckId.MAIN] is RenderMode.PAGED

        # Split open/close and zoom in/out keep panel 0's policy.
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        assert area.state.panels[0].views.main is DeckView.PAGE_CARDS
        assert area.panel(0).view_policy(DeckId.MAIN) is DeckView.PAGE_CARDS
        assert area.panel(1).view_policy(DeckId.MAIN) is DeckView.AUTO
        # Same-key unsplit keeps the focused panel: focus panel 0 first so
        # its policy is the one that survives the close.
        detail.toggle_deck_focus()
        await pilot.pause()
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        assert area.state.panels[0].views.main is DeckView.PAGE_CARDS
        assert area.panel(0).view_policy(DeckId.MAIN) is DeckView.PAGE_CARDS
        detail.toggle_deck_zoom()
        await pilot.pause()
        assert area.panel(0).view_policy(DeckId.MAIN) is DeckView.PAGE_CARDS
        detail.toggle_deck_zoom()
        await pilot.pause()
        assert area.state.panels[0].views.main is DeckView.PAGE_CARDS
        assert area.panel(0).view_policy(DeckId.MAIN) is DeckView.PAGE_CARDS
        assert panel._render_mode[DeckId.MAIN] is RenderMode.PAGED


async def test_resize_under_fixed_policy_never_transitions() -> None:
    """A resize re-decision under a fixed policy changes no mode or card."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=0, blocks=1000)
        panel = await _panel(app)
        panel.show_main_document(
            _document("s1", _reply_card(3), digest="view-resize"), "reply"
        )
        await _settle(pilot, panel, DeckView.PAGE_CARDS)
        panel.set_view_policy(DeckId.MAIN, DeckView.PAGE_CARDS)
        await pilot.pause()
        generation = panel._view_generation
        mode = panel._render_mode[DeckId.MAIN]
        block_mode = panel.block_mode_for_active_card()
        active = panel._main_active_card

        panel._handle_resize_decision()
        await pilot.pause()
        await pilot.pause()
        assert panel.view_policy(DeckId.MAIN) is DeckView.PAGE_CARDS
        assert panel._render_mode[DeckId.MAIN] is mode
        assert panel.block_mode_for_active_card() is block_mode
        assert panel._main_active_card == active
        assert panel._view_generation == generation


async def test_reset_to_auto_matches_fresh_decision() -> None:
    """Resetting to AUTO re-decides exactly like a fresh AUTO subject."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=0, blocks=1000)
        panel = await _panel(app)
        panel.show_main_document(
            _document("s1", _reply_card(3), digest="view-reset"), "reply"
        )
        await _settle(pilot, panel, DeckView.PAGE_CARDS)
        fresh_mode = panel._render_mode[DeckId.MAIN]
        fresh_block = panel.block_mode_for_active_card()

        panel.set_view_policy(DeckId.MAIN, DeckView.SPREAD)
        await _settle(pilot, panel, DeckView.SPREAD)

        panel.set_view_policy(DeckId.MAIN, DeckView.AUTO)
        await _settle(pilot, panel, DeckView.PAGE_CARDS)
        assert panel.view_policy(DeckId.MAIN) is DeckView.AUTO
        assert panel._render_mode[DeckId.MAIN] is fresh_mode
        assert panel.block_mode_for_active_card() is fresh_block


async def test_rapid_view_changes_end_on_first_anchor() -> None:
    """Rapid P-P-P reuses the pending anchor and lands on its block."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=1000, blocks=1000)
        panel = await _panel(app)
        panel.show_main_document(
            _document("s1", _reply_card(3), digest="view-rapid"), "reply"
        )
        await _settle(pilot, panel, DeckView.SPREAD)
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
        await _settle(pilot, panel, DeckView.PAGE_BLOCKS)
        assert view.active_block_id("reply") == "b1"
        expected = await _expected_row(pilot, panel)
        await wait_for(pilot, lambda: int(_scroll(panel).scroll_y) == expected)
        assert _following(panel) is False


async def test_partial_documents_store_without_applying() -> None:
    """Partial documents store the policy; the next full paint applies it."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=0, blocks=1000)
        panel = await _panel(app)
        panel.show_main_document(
            _document("s1", _reply_card(3), digest="view-partial"), "reply"
        )
        await _settle(pilot, panel, DeckView.PAGE_CARDS)

        panel.show_main_document(
            _document("s1", _reply_card(3), digest="view-partial-hdr", partial=True),
            "reply",
        )
        await pilot.pause()
        panel.set_view_policy(DeckId.MAIN, DeckView.PAGE_BLOCKS)
        await pilot.pause()
        assert panel.view_policy(DeckId.MAIN) is DeckView.PAGE_BLOCKS

        panel.show_main_document(
            _document("s1", _reply_card(3), digest="view-partial-full"), "reply"
        )
        await _settle(pilot, panel, DeckView.PAGE_BLOCKS)
        assert panel._render_mode[DeckId.MAIN] is RenderMode.PAGED
        assert panel.block_mode_for_active_card() is RenderMode.PAGED


async def test_persisted_view_restores_after_restart() -> None:
    """A snapshot round trip restores the fixed view on a fresh panel."""
    from sase.ace.tui.models.agent_deck_persistence import (
        area_state_from_snapshot,
        snapshot_from_area_state,
    )

    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=0, blocks=1000)
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        area = detail.deck_area
        panel = area.panel(0)
        panel.show_main_document(
            _document("s1", _reply_card(3), digest="view-restart"), "reply"
        )
        await _settle(pilot, panel, DeckView.PAGE_CARDS)

        area.set_panel_view(0, DeckId.MAIN, DeckView.PAGE_BLOCKS)
        await _settle(pilot, panel, DeckView.PAGE_BLOCKS)
        snapshot = snapshot_from_area_state(area.state)
        restored = area_state_from_snapshot(snapshot)
        assert restored.panels[0].views.main is DeckView.PAGE_BLOCKS

        # Simulated restart: the panel forgets, the snapshot restores.
        panel.set_view_policy(DeckId.MAIN, DeckView.AUTO)
        assert panel.sync_view_policies(restored.panels[0].views) is True
        panel.show_main_document(
            _document("s1", _reply_card(3), digest="view-restart-2"), "reply"
        )
        await _settle(pilot, panel, DeckView.PAGE_BLOCKS)
        assert panel.view_policy(DeckId.MAIN) is DeckView.PAGE_BLOCKS


@pytest.mark.parametrize(
    ("deck_pin", "block_pin", "first"),
    (
        (0.0, 0.0, DeckView.PAGE_CARDS),
        (0.0, 1000.0, DeckView.SPREAD),
        (1000.0, 1000.0, DeckView.PAGE_BLOCKS),
    ),
)
async def test_cycle_focused_deck_view_from_auto(
    deck_pin: float, block_pin: float, first: DeckView
) -> None:
    """The first cycle from AUTO fixes the next wider layout (first_fix)."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=deck_pin, blocks=block_pin)
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        panel.show_main_document(
            _document("s1", _reply_card(3), digest=f"view-cycle-{first.value}"),
            "reply",
        )
        await pilot.pause()
        await pilot.pause()
        assert panel.view_policy(DeckId.MAIN) is DeckView.AUTO

        result = detail.cycle_focused_deck_view()
        assert result == (first, True)
        await _settle(pilot, panel, first)
        assert panel.view_policy(DeckId.MAIN) is first

        second = detail.cycle_focused_deck_view()
        assert second is not None
        assert second[1] is False
        await _settle(pilot, panel, second[0])

        assert detail.set_focused_deck_view(DeckView.PAGE_CARDS) is True
        await _settle(pilot, panel, DeckView.PAGE_CARDS)
        assert panel.view_policy(DeckId.MAIN) is DeckView.PAGE_CARDS


async def test_cycle_unavailable_for_tools_empty_partial_single() -> None:
    """The cycle is gated for Tools, empty, partial, and single-card decks."""
    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        _pin(app, deck=0, blocks=0)
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)

        panel.set_deck(DeckId.TOOLS)
        await pilot.pause()
        assert detail.cycle_focused_deck_view() is None
        assert detail.set_focused_deck_view(DeckView.SPREAD) is False
        panel.set_deck(DeckId.MAIN)
        await pilot.pause()

        panel.show_main_document(
            MainDeckDocument(cards=(), subject="empty", partial=False, digest="e1"),
            None,
        )
        await pilot.pause()
        assert detail.cycle_focused_deck_view() is None

        panel.show_main_document(
            _document("s1", _reply_card(3), digest="view-gate-hdr", partial=True),
            "reply",
        )
        await pilot.pause()
        assert detail.cycle_focused_deck_view() is None

        single = MainDeckDocument(
            cards=(context_card(Text("only")),),
            subject="single",
            partial=False,
            digest="single-1",
        )
        panel.show_main_document(single, "context")
        await pilot.pause()
        assert detail.cycle_focused_deck_view() is None
        assert panel.view_policy(DeckId.MAIN) is DeckView.AUTO


async def test_final_panel_shows_no_badge_and_no_cycle() -> None:
    """A FINAL panel has no badge and P is unavailable.

    Cross-epic R1 (sase-1b2.14 landed): FINAL stays permanently AUTO.
    """
    from sase.ace.tui.widgets.decks.titles import _badge_variants

    app = _DetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        panel.set_deck(DeckId.FINAL)
        await pilot.pause()
        assert panel.deck is DeckId.FINAL
        assert panel.view_policy(DeckId.FINAL) is DeckView.AUTO
        assert panel.next_view() is None
        assert panel.deck_view_cycle_available is False
        assert panel._chrome_view(DeckId.FINAL) is None
        assert _badge_variants(
            DeckId.FINAL,
            panel.resolved_view(),
            accent="#AF87FF",
            focused=True,
        ) == (None, None, None)
        assert detail.cycle_focused_deck_view() is None
        assert detail.set_focused_deck_view(DeckView.SPREAD) is False
