from __future__ import annotations

from pathlib import Path

from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckLayout
from tests.ace.tui.widgets.decks._deck_split_test_support import (
    DetailApp,
    make_agent,
    make_artifact_agent,
    pin_paged,
)


async def test_backslash_opens_top_bottom_and_keeps_focus(tmp_path: Path) -> None:
    app = DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        assert detail.deck_layout is DeckLayout.SINGLE
        detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
        await pilot.pause()
        area = detail.deck_area
        assert area.state.layout is DeckLayout.TOP_BOTTOM
        assert area.state.focused == 0
        assert area.state.ratio == 50
        assert len(area.visible_panels()) == 2
        assert area.panel(0).has_class("-focused")
        assert area.panel(1).has_class("-unfocused")
        # CSS classes synced.
        assert area.has_class("-top-bottom")
        assert area.has_class("-ratio-50")


async def test_pipe_opens_left_right_and_unsplit_keeps_focused(tmp_path: Path) -> None:
    app = DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        assert detail.deck_area.state.layout is DeckLayout.LEFT_RIGHT
        assert detail.deck_area.state.focused == 0
        detail.toggle_deck_focus()
        await pilot.pause()
        assert detail.deck_area.state.focused == 1
        focused_widget = detail.deck_area.panel(1)
        focused_deck = focused_widget.deck
        # Same-key unsplit keeps the focused panel, not panel 0.
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        assert detail.deck_layout is DeckLayout.SINGLE
        assert detail.deck_area.state.focused == 1
        assert detail.deck_area.panel(1) is focused_widget
        assert detail.deck_area.panel(1).deck is focused_deck


async def test_unsplit_keeps_first_when_first_focused(tmp_path: Path) -> None:
    app = DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        panel0 = detail.deck_area.panel(0)
        card_before = panel0.main_view.active_card_id
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        assert detail.deck_area.state.focused == 0
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        assert detail.deck_layout is DeckLayout.SINGLE
        assert detail.deck_area.panel(0) is panel0
        assert detail.deck_area.panel(0).main_view.active_card_id == card_before


async def test_structural_keys_never_remount_survivors(tmp_path: Path) -> None:
    """Split, unsplit, turn, focus, resize and zoom keep widget identity."""
    app = DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        area = detail.deck_area
        widget0 = area.panel(0)
        widget1 = area.panel(1)
        scroll0 = widget0.main_view
        detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
        await pilot.pause()
        assert area.panel(0) is widget0
        assert area.panel(1) is widget1
        assert area.panel(0).main_view is scroll0
        detail.toggle_deck_focus()
        await pilot.pause()
        assert area.state.focused == 1
        detail.toggle_deck_focus()
        await pilot.pause()
        assert area.state.focused == 0
        assert area.panel(0) is widget0
        assert area.panel(1) is widget1
        card_before = widget0.main_view.active_card_id
        detail.step_deck_ratio(True)
        await pilot.pause()
        assert area.panel(0) is widget0
        assert area.panel(1) is widget1
        detail.turn_deck_layout()
        await pilot.pause()
        assert area.panel(0) is widget0
        assert area.panel(1) is widget1
        detail.toggle_deck_zoom()
        await pilot.pause()
        assert area.focused_panel() is widget0
        detail.toggle_deck_zoom()
        await pilot.pause()
        assert area.panel(0) is widget0
        assert area.panel(1) is widget1
        assert area.panel(0).main_view is scroll0
        assert area.panel(0).main_view.active_card_id == card_before
        # Same-key unsplit keeps the focused panel's widget and scroll.
        # The turn above left a LEFT_RIGHT outer axis, so that key unsplits.
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        assert detail.deck_layout is DeckLayout.SINGLE
        assert area.focused_panel() is widget0


async def test_turn_keeps_widget_identities(tmp_path: Path) -> None:
    app = DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
        await pilot.pause()
        panel0_before = detail.deck_area.panel(0)
        panel1_before = detail.deck_area.panel(1)
        main0_before = panel0_before.main_view
        detail.turn_deck_layout()
        await pilot.pause()
        assert detail.deck_area.panel(0) is panel0_before
        assert detail.deck_area.panel(1) is panel1_before
        assert detail.deck_area.panel(0).main_view is main0_before


async def test_ctrl_f_flips_focus_and_single_noop(tmp_path: Path) -> None:
    app = DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        # SINGLE no-op.
        detail.toggle_deck_focus()
        await pilot.pause()
        assert detail.deck_area.state.focused == 0
        detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
        await pilot.pause()
        assert detail.deck_area.state.focused == 0
        detail.toggle_deck_focus()
        await pilot.pause()
        assert detail.deck_area.state.focused == 1
        assert detail.deck_area.panel(1).has_class("-focused")
        assert detail.deck_area.panel(0).has_class("-unfocused")


async def test_ratio_steps_and_clamp() -> None:
    app = DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_agent(status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        detail.toggle_deck_focus()
        await pilot.pause()
        # Focus is panel 1: grow shrinks panel 0's share.
        detail.step_deck_ratio(True)
        await pilot.pause()
        assert detail.deck_area.state.ratio == 30
        detail.step_deck_ratio(True)
        await pilot.pause()
        assert detail.deck_area.state.ratio == 30
        detail.step_deck_ratio(False)
        await pilot.pause()
        assert detail.deck_area.state.ratio == 50
        # Flip focus to panel 0: grow expands panel 0.
        detail.toggle_deck_focus()
        await pilot.pause()
        detail.step_deck_ratio(True)
        await pilot.pause()
        assert detail.deck_area.state.ratio == 70
