from __future__ import annotations

import pytest
from rich.text import Text

from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.card_part import context_card
from sase.ace.tui.widgets.decks.main_document import MainDeckDocument
from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout, DeckView, RenderMode
from tests.ace.tui.widgets.decks._deck_view_main_support import (
    MainDetailApp,
    get_panel,
    make_document,
    make_reply_card,
    pin_settings,
    settle_view,
)


async def test_fixed_policy_survives_navigation() -> None:
    """A fixed policy survives subjects, cards, deck switches, split, zoom."""
    app = MainDetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pin_settings(app, deck=0, blocks=1000)
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        area = detail.deck_area
        panel = area.panel(0)
        panel.show_main_document(
            make_document("s1", make_reply_card(3), digest="view-survive"), "reply"
        )
        await settle_view(pilot, panel, DeckView.PAGE_CARDS)
        area.set_panel_view(0, DeckId.MAIN, DeckView.PAGE_CARDS)
        assert panel.view_policy(DeckId.MAIN) is DeckView.PAGE_CARDS
        assert area.state.panels[0].views.main is DeckView.PAGE_CARDS

        # j/k: a new subject lands with today's rules under the fixed policy.
        panel.show_main_document(
            make_document("s2", make_reply_card(3), digest="view-survive-2"), "reply"
        )
        await settle_view(pilot, panel, DeckView.PAGE_CARDS)
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
        await settle_view(pilot, panel, DeckView.PAGE_CARDS)
        assert panel.view_policy(DeckId.MAIN) is DeckView.PAGE_CARDS
        assert panel._render_mode[DeckId.MAIN] is RenderMode.PAGED

        # Split open/close and zoom in/out keep panel 0's policy.
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        assert area.state.panels[0].views.main is DeckView.PAGE_CARDS
        assert area.panel(0).view_policy(DeckId.MAIN) is DeckView.PAGE_CARDS
        assert area.panel(1).view_policy(DeckId.MAIN) is DeckView.AUTO
        # Same-key unsplit keeps the focused panel, which remains panel 0.
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
    app = MainDetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pin_settings(app, deck=0, blocks=1000)
        panel = await get_panel(app)
        panel.show_main_document(
            make_document("s1", make_reply_card(3), digest="view-resize"), "reply"
        )
        await settle_view(pilot, panel, DeckView.PAGE_CARDS)
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


async def test_resize_block_refresh_keeps_preferred_main_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resize repaint prefers the sticky card over a stale active card."""
    app = MainDetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pin_settings(app)
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        document = make_document(
            "resize-subject", make_reply_card(3), digest="resize-sticky"
        )
        panel.show_main_document(document, "reply")
        detail.set_deck_preferred_card(0, "reply")
        await pilot.pause()
        assert panel.main_view.active_card_id == "reply"

        # Resize/repaint can leave the view's active card behind the sticky
        # choice. A block refresh must restore the pane's preferred card.
        panel.main_view.show_card("context")
        panel._main_active_card = "context"
        assert detail.deck_area.state.panels[0].preferred_card == "reply"
        monkeypatch.setattr(panel, "needs_document_block_refresh", lambda _deck: True)
        panel._refresh_main_mode_for_shown()
        await pilot.pause()

        assert panel.main_view.active_card_id == "reply"
        assert panel._main_active_card == "reply"


async def test_spread_to_paged_resize_keeps_preferred_main_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mode change does not let stale spread focus outrank sticky Main."""
    app = MainDetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pin_settings(app)
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        document = make_document(
            "resize-transition", make_reply_card(3), digest="resize-transition"
        )
        panel.show_main_document(document, "reply")
        detail.set_deck_preferred_card(0, "reply")
        await pilot.pause()

        panel.main_view.show_card("context")
        panel._main_active_card = "context"
        assert detail.deck_area.state.panels[0].preferred_card == "reply"
        panel._render_mode[DeckId.MAIN] = RenderMode.SPREAD
        panel._mode_subject[DeckId.MAIN] = document.subject
        monkeypatch.setattr(
            panel,
            "_decide_document_mode",
            lambda *_args, **_kwargs: RenderMode.PAGED,
        )

        panel._refresh_main_mode_for_shown()
        await pilot.pause()

        assert panel.main_view.active_card_id == "reply"
        assert panel._main_active_card == "reply"


async def test_reset_to_auto_matches_fresh_decision() -> None:
    """Resetting to AUTO re-decides exactly like a fresh AUTO subject."""
    app = MainDetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pin_settings(app, deck=0, blocks=1000)
        panel = await get_panel(app)
        panel.show_main_document(
            make_document("s1", make_reply_card(3), digest="view-reset"), "reply"
        )
        await settle_view(pilot, panel, DeckView.PAGE_CARDS)
        fresh_mode = panel._render_mode[DeckId.MAIN]
        fresh_block = panel.block_mode_for_active_card()

        panel.set_view_policy(DeckId.MAIN, DeckView.SPREAD)
        await settle_view(pilot, panel, DeckView.SPREAD)

        panel.set_view_policy(DeckId.MAIN, DeckView.AUTO)
        await settle_view(pilot, panel, DeckView.PAGE_CARDS)
        assert panel.view_policy(DeckId.MAIN) is DeckView.AUTO
        assert panel._render_mode[DeckId.MAIN] is fresh_mode
        assert panel.block_mode_for_active_card() is fresh_block


async def test_persisted_view_restores_after_restart() -> None:
    """A snapshot round trip restores the fixed view on a fresh panel."""
    from sase.ace.tui.models.agent_deck_persistence import (
        area_state_from_snapshot,
        snapshot_from_area_state,
    )

    app = MainDetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pin_settings(app, deck=0, blocks=1000)
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        area = detail.deck_area
        panel = area.panel(0)
        panel.show_main_document(
            make_document("s1", make_reply_card(3), digest="view-restart"), "reply"
        )
        await settle_view(pilot, panel, DeckView.PAGE_CARDS)

        area.set_panel_view(0, DeckId.MAIN, DeckView.PAGE_BLOCKS)
        await settle_view(pilot, panel, DeckView.PAGE_BLOCKS)
        snapshot = snapshot_from_area_state(area.state)
        restored = area_state_from_snapshot(snapshot)
        assert restored.panels[0].views.main is DeckView.PAGE_BLOCKS

        # Simulated restart: the panel forgets, the snapshot restores.
        panel.set_view_policy(DeckId.MAIN, DeckView.AUTO)
        assert panel.sync_view_policies(restored.panels[0].views) is True
        panel.show_main_document(
            make_document("s1", make_reply_card(3), digest="view-restart-2"), "reply"
        )
        await settle_view(pilot, panel, DeckView.PAGE_BLOCKS)
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
    app = MainDetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pin_settings(app, deck=deck_pin, blocks=block_pin)
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        panel.show_main_document(
            make_document("s1", make_reply_card(3), digest=f"view-cycle-{first.value}"),
            "reply",
        )
        await pilot.pause()
        await pilot.pause()
        assert panel.view_policy(DeckId.MAIN) is DeckView.AUTO

        result = detail.cycle_focused_deck_view()
        assert result == (first, True)
        await settle_view(pilot, panel, first)
        assert panel.view_policy(DeckId.MAIN) is first

        second = detail.cycle_focused_deck_view()
        assert second is not None
        assert second[1] is False
        await settle_view(pilot, panel, second[0])

        assert detail.set_focused_deck_view(DeckView.PAGE_CARDS) is True
        await settle_view(pilot, panel, DeckView.PAGE_CARDS)
        assert panel.view_policy(DeckId.MAIN) is DeckView.PAGE_CARDS


async def test_cycle_unavailable_for_tools_empty_partial_single() -> None:
    """The cycle is gated for Tools, empty, partial, and single-card decks."""
    app = MainDetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pin_settings(app, deck=0, blocks=0)
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
            make_document(
                "s1", make_reply_card(3), digest="view-gate-hdr", partial=True
            ),
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

    app = MainDetailApp()
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


async def test_spread_title_cue_and_paged_tabs_flip() -> None:
    """Spread titles use a here-name cue; paging restores tabs; the footer flips.

    The reply is taller than the viewport so the viewport-precise spread cue
    keeps a direction (fully visible later cards are dropped, so a tiny deck
    would read "both cards in view" instead).
    """
    app = MainDetailApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        pin_settings(app, deck=1000.0, blocks=1000.0)
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        panel.show_main_document(
            make_document(
                "s1", make_reply_card(2, lines_per_block=30), digest="scope-spread"
            ),
            "reply",
        )
        await settle_view(pilot, panel, DeckView.SPREAD)
        panel.refresh_chrome()
        title = panel._border_title.plain
        assert "\u2503" not in title
        assert "SPREAD" in title
        assert "Context" in title
        assert "Reply" in title
        assert "\u25b4" in title or "\u25be" in title
        assert panel.deck_cards_spread is True
        before = title
        panel.show_main_document(
            make_document(
                "s1",
                make_reply_card(2, lines_per_block=30),
                digest="scope-partial",
                partial=True,
            ),
            "reply",
        )
        await pilot.pause()
        panel.refresh_chrome()
        assert panel._border_title.plain == before
        panel.show_main_document(
            make_document(
                "s1", make_reply_card(2, lines_per_block=30), digest="scope-spread-2"
            ),
            "reply",
        )
        await settle_view(pilot, panel, DeckView.SPREAD)
        # Jump toward the other card so the here-name and cue swap.
        if "\u25be" in panel._border_title.plain:
            detail.cycle_focused_deck_card(1)
        else:
            detail.cycle_focused_deck_card(-1)
        await pilot.pause()
        panel.refresh_chrome()
        jumped = panel._border_title.plain
        assert jumped != before
        assert "\u2503" not in jumped
        assert "Context" in jumped
        assert "Reply" in jumped
        assert "\u25b4" in jumped or "\u25be" in jumped
        pin_settings(app, deck=0.0, blocks=0.0)
        panel.show_main_document(
            make_document("s1", make_reply_card(3), digest="scope-paged"),
            "reply",
        )
        await settle_view(pilot, panel, DeckView.PAGE_BLOCKS)
        panel.refresh_chrome()
        paged = panel._border_title.plain
        assert "\u2503" in paged or "\u2039" in paged
        assert panel.deck_cards_spread is False
