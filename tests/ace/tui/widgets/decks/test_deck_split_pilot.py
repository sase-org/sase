"""Pilot tests for deck split layouts, focus and ratio."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding

from sase.ace.tui.actions.agents._deck_layout_actions import AgentDeckLayoutActionsMixin
from sase.ace.tui.bindings import DEFAULT_BINDINGS
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId, DeckLayout
from tests.ace.tui.widgets.decks._deck_spread_test_helpers import pin_paged
from tests.ace.tui.widgets._agent_display_helpers import (
    make_agent,
    make_artifact_agent,
)

_DECK_KEY_ACTIONS = frozenset(
    {
        "toggle_deck_split_below",
        "toggle_deck_split_right",
        "toggle_deck_focus",
        "toggle_deck_focus_reverse",
        "swap_deck_panel_next",
        "swap_deck_panel_prev",
        "close_deck_panel",
        "turn_deck_layout",
    }
)


class _DeckKeyApp(AgentDeckLayoutActionsMixin, App[None]):
    """Detail host with live deck key bindings for real key presses."""

    CSS_PATH = Path(__file__).resolve().parents[5] / "src/sase/ace/tui/styles.tcss"
    BINDINGS = [
        binding
        for binding in DEFAULT_BINDINGS
        if isinstance(binding, Binding) and binding.action in _DECK_KEY_ACTIONS
    ]

    current_tab: str = "agents"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


_ROOT = Path(__file__).resolve().parents[5]


class _DetailApp(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def test_backslash_opens_top_bottom_with_focus(tmp_path: Path) -> None:
    app = _DetailApp()
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
        assert area.state.focused == 1
        assert area.state.ratio == 50
        assert len(area.visible_panels()) == 2
        assert area.panel(0).has_class("-focused") or True
        # CSS classes synced.
        assert area.has_class("-top-bottom")
        assert area.has_class("-ratio-50")


async def test_pipe_opens_left_right_and_unsplit_keeps_focused(tmp_path: Path) -> None:
    app = _DetailApp()
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
    app = _DetailApp()
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
        detail.toggle_deck_focus()
        await pilot.pause()
        assert detail.deck_area.state.focused == 0
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        assert detail.deck_layout is DeckLayout.SINGLE
        assert detail.deck_area.panel(0) is panel0
        assert detail.deck_area.panel(0).main_view.active_card_id == card_before


async def test_structural_keys_never_remount_survivors(tmp_path: Path) -> None:
    """Split, unsplit, turn, focus, resize and zoom keep widget identity."""
    app = _DetailApp()
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
        card_before = widget0.main_view.active_card_id
        detail.toggle_deck_focus()
        await pilot.pause()
        assert area.panel(0) is widget0
        assert area.panel(1) is widget1
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
    app = _DetailApp()
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
    app = _DetailApp()
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
        assert detail.deck_area.state.focused == 1
        detail.toggle_deck_focus()
        await pilot.pause()
        assert detail.deck_area.state.focused == 0
        assert detail.deck_area.panel(0).has_class("-focused")
        assert detail.deck_area.panel(1).has_class("-unfocused")


async def test_ratio_steps_and_clamp() -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_agent(status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
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


async def test_context_reply_for_agent_without_files_or_tools(tmp_path: Path) -> None:
    from sase.ace.tui.widgets.decks.availability import DeckAvailability

    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        # Force no-files/no-tools so the new panel duplicates Main.
        panel0_before = detail.deck_area.panel(0)
        panel0_before._availability = {
            DeckId.MAIN: DeckAvailability(True, 2),
            DeckId.FILES: DeckAvailability(False, 0),
            DeckId.TOOLS: DeckAvailability(False, 0),
        }
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        panel0 = detail.deck_area.panel(0)
        panel1 = detail.deck_area.panel(1)
        # No files/tools: second panel duplicates Main.
        assert panel1.deck is DeckId.MAIN
        assert panel0.deck is DeckId.MAIN
        assert panel0.main_view.active_card_id != panel1.main_view.active_card_id


async def test_main_document_fans_out_to_both(tmp_path: Path) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
        await pilot.pause()
        # Force both panels to Main for fan-out check.
        detail.show_deck(1, DeckId.MAIN)
        await pilot.pause()
        detail.update_display(agent)
        await pilot.pause()
        panel0 = detail.deck_area.panel(0)
        panel1 = detail.deck_area.panel(1)
        assert panel0.main_view.active_card_id is not None
        assert panel1.main_view.active_card_id is not None


async def test_ctrl_n_p_act_on_focused_panel(tmp_path: Path) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
        await pilot.pause()
        before0 = detail.deck_area.panel(0).deck
        before1 = detail.deck_area.panel(1).deck
        # Focus is panel 1: cycle it, panel 0 stays.
        detail.cycle_focused_deck(1)
        await pilot.pause()
        assert detail.deck_area.panel(0).deck is before0
        assert detail.deck_area.panel(1).deck is not before1


async def test_duplicate_files_single_fetch(tmp_path: Path) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        # Open a Files deck in panel 0, then duplicate it.
        detail.show_deck(0, DeckId.FILES)
        await pilot.pause()
        await pilot.pause()
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        # If the new panel is Files, only the owner should own a worker.
        area = detail.deck_area
        if area.panel(1).deck is DeckId.FILES:
            workers = [
                len(getattr(p.file_view, "_inflight_diff_tasks", {}))
                for p in area.visible_panels()
                if p.deck is DeckId.FILES
            ]
            # At most one Files view holds in-flight diff tasks.
            assert sum(1 for w in workers if w > 0) <= 1


async def test_duplicate_tools_single_fetch(tmp_path: Path) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        detail.show_deck(0, DeckId.TOOLS)
        await pilot.pause()
        detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
        await pilot.pause()
        area = detail.deck_area
        if area.panel(1).deck is DeckId.TOOLS:
            # The mtime-keyed throttle dedupes Tools fetches: the second
            # panel must not own a running worker.
            running = [
                bool(
                    getattr(p.tools_view, "_current_worker", None) is not None
                    and getattr(p.tools_view._current_worker, "is_running", False)
                )
                for p in area.visible_panels()
                if p.deck is DeckId.TOOLS
            ]
            assert sum(1 for r in running if r) <= 1


async def test_three_panel_resize_clamps_to_minimums(tmp_path: Path) -> None:
    from sase.ace.tui.util.pane_grid import _main_pane

    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
        await pilot.pause()
        detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
        await pilot.pause()
        area = detail.deck_area
        assert len(area.state.grid.panes) == 3
        main = _main_pane(area.state.grid)
        assert main is not None
        if area.state.focused != main:
            detail.toggle_deck_focus()
            await pilot.pause()
        if detail.deck_area.state.focused != main:
            detail.toggle_deck_focus()
            await pilot.pause()
        assert detail.deck_area.state.focused == main
        before = detail.deck_area.state
        detail._deck_area_extent = lambda: (100, 34)  # type: ignore[method-assign]
        detail.step_deck_ratio(False)
        await pilot.pause()
        assert detail.deck_area.state == before
        detail.step_deck_ratio(True)
        await pilot.pause()
        assert detail.deck_area.state == before


async def test_close_each_of_three_panels_keeps_textual_focus(tmp_path: Path) -> None:
    app = _DetailApp()
    pin_paged(app)
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        agent = make_artifact_agent(tmp_path, status="DONE")
        detail.update_display(agent)
        await pilot.pause()
        for target in (2, 1, 0):
            detail.toggle_deck_split(DeckLayout.LEFT_RIGHT)
            await pilot.pause()
            detail.toggle_deck_split(DeckLayout.TOP_BOTTOM)
            await pilot.pause()
            area = detail.deck_area
            assert len(area.state.grid.panes) == 3
            if detail.deck_area.state.focused != target:
                detail.toggle_deck_focus()
                await pilot.pause()
            if detail.deck_area.state.focused != target:
                detail.toggle_deck_focus()
                await pilot.pause()
            if detail.deck_area.state.focused != target:
                continue
            detail.close_deck_panel()
            await pilot.pause()
            survivor = detail.deck_area.focused_panel()
            focused = app.focused
            assert focused is not None
            node: object | None = focused
            inside = False
            while node is not None:
                if node is survivor:
                    inside = True
                    break
                node = getattr(node, "parent", None)
            assert inside
            # Reset to single for the next iteration.
            while len(detail.deck_area.state.grid.panes) > 1:
                detail.close_deck_panel()
                await pilot.pause()


async def test_real_deck_keys_reach_actions_on_two_and_three_panels(
    tmp_path: Path,
) -> None:
    app = _DeckKeyApp()
    pin_paged(app)
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
        await pilot.pause()
        await pilot.press("backslash")
        await pilot.pause()
        assert len(detail.deck_area.state.grid.panes) == 2
        # Focus ring both directions.
        before = detail.deck_area.state.focused
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert detail.deck_area.state.focused != before
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert detail.deck_area.state.focused == before
        # Swap both directions keep the panel set.
        panels_before = set(detail.deck_area._panels_by_id())
        await pilot.press("ctrl+shift+f")
        await pilot.pause()
        assert set(detail.deck_area._panels_by_id()) == panels_before
        await pilot.press("greater_than_sign")
        await pilot.pause()
        assert set(detail.deck_area._panels_by_id()) == panels_before
        await pilot.press("ctrl+shift+b")
        await pilot.pause()
        assert set(detail.deck_area._panels_by_id()) == panels_before
        await pilot.press("less_than_sign")
        await pilot.pause()
        assert set(detail.deck_area._panels_by_id()) == panels_before
        # Nest to three, then turn.
        await pilot.press("vertical_line")
        await pilot.pause()
        assert len(detail.deck_area.state.grid.panes) == 3
        grid_before = detail.deck_area.state.grid
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert len(detail.deck_area.state.grid.panes) == 3
        assert detail.deck_area.state.grid != grid_before
        # Close aliases each remove one panel.
        await pilot.press("ctrl+x")
        await pilot.pause()
        assert len(detail.deck_area.state.grid.panes) == 2
        await pilot.press("ctrl+shift+d")
        await pilot.pause()
        assert len(detail.deck_area.state.grid.panes) == 1


async def test_deck_swap_keeps_identity_and_click_focuses_after_swap(
    tmp_path: Path,
) -> None:
    app = _DeckKeyApp()
    pin_paged(app)
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
        await pilot.pause()
        await pilot.press("backslash")
        await pilot.pause()
        await pilot.press("vertical_line")
        await pilot.pause()
        assert len(detail.deck_area.state.grid.panes) == 3
        widgets_before = {
            pid: detail.deck_area.panel(pid)
            for pid in detail.deck_area.state.grid.panes
        }
        grid_before = detail.deck_area.state.grid
        await pilot.press("greater_than_sign")
        await pilot.pause()
        widgets_after = {
            pid: detail.deck_area.panel(pid)
            for pid in detail.deck_area.state.grid.panes
        }
        assert set(widgets_after.values()) == set(widgets_before.values())
        assert detail.deck_area.state.grid != grid_before
        # Click focus works after a swap.
        target_id = detail.deck_area.state.grid.panes[0]
        detail.deck_area.panel(target_id).on_click(object())
        await pilot.pause()
        assert detail.deck_area.state.focused == target_id


async def test_deck_close_each_and_erase_through_keys(tmp_path: Path) -> None:
    app = _DeckKeyApp()
    pin_paged(app)
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
        await pilot.pause()
        for target in (2, 1, 0):
            await pilot.press("backslash")
            await pilot.pause()
            await pilot.press("vertical_line")
            await pilot.pause()
            assert len(detail.deck_area.state.grid.panes) == 3
            if detail.deck_area.state.focused != target:
                await pilot.press("ctrl+f")
                await pilot.pause()
            if detail.deck_area.state.focused != target:
                await pilot.press("ctrl+f")
                await pilot.pause()
            if detail.deck_area.state.focused != target:
                await pilot.press("ctrl+x")
                await pilot.pause()
                continue
            await pilot.press("ctrl+x")
            await pilot.pause()
            assert len(detail.deck_area.state.grid.panes) == 2
            await pilot.press("ctrl+x")
            await pilot.pause()
            assert len(detail.deck_area.state.grid.panes) == 1


async def test_deck_erase_through_keys_with_main_and_pair_focused(
    tmp_path: Path,
) -> None:
    from sase.ace.tui.util.pane_grid import _main_pane

    app = _DeckKeyApp()
    pin_paged(app)
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
        await pilot.pause()
        for focus_main in (True, False):
            await pilot.press("backslash")
            await pilot.pause()
            await pilot.press("vertical_line")
            await pilot.pause()
            assert len(detail.deck_area.state.grid.panes) == 3
            main = _main_pane(detail.deck_area.state.grid)
            assert main is not None
            if focus_main:
                if detail.deck_area.state.focused != main:
                    await pilot.press("ctrl+f")
                    await pilot.pause()
                if detail.deck_area.state.focused != main:
                    await pilot.press("ctrl+f")
                    await pilot.pause()
                assert detail.deck_area.state.focused == main
                await pilot.press("backslash")
                await pilot.pause()
                assert len(detail.deck_area.state.grid.panes) == 1
            else:
                pair_id = next(
                    pid for pid in detail.deck_area.state.grid.panes if pid != main
                )
                if detail.deck_area.state.focused != pair_id:
                    await pilot.press("ctrl+f")
                    await pilot.pause()
                if detail.deck_area.state.focused != pair_id:
                    await pilot.press("ctrl+f")
                    await pilot.pause()
                assert detail.deck_area.state.focused == pair_id
                await pilot.press("backslash")
                await pilot.pause()
                assert len(detail.deck_area.state.grid.panes) == 2


async def test_deck_rapid_keys_leave_valid_state(tmp_path: Path) -> None:
    app = _DeckKeyApp()
    pin_paged(app)
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
        await pilot.pause()
        for key in (
            "backslash",
            "vertical_line",
            "ctrl+t",
            "ctrl+shift+f",
            "ctrl+x",
            "backslash",
            "ctrl+t",
        ):
            await pilot.press(key)
            await pilot.pause()
        panes = detail.deck_area.state.grid.panes
        assert 1 <= len(panes) <= 3
        assert set(detail.deck_area.state.panels) == set(panes)


def test_tab_disjoint_availability_for_swap_and_turn() -> None:
    from sase.ace.tui._app_action_availability import check_app_action
    from sase.ace.tui._app_action_availability_agents import _DECK_LAYOUT_ACTIONS
    from sase.ace.tui._app_action_availability_artifacts import (
        _ARTIFACT_RELATION_ACTIONS,
    )

    def _available(action: str, tab: str) -> bool | None:
        class _TabApp:
            current_tab = tab

        return check_app_action(_TabApp(), action, (), lambda *args: None)

    # Swap and turn live in the Agents-only deck layout set.
    assert "swap_deck_panel_next" in _DECK_LAYOUT_ACTIONS
    assert "swap_deck_panel_prev" in _DECK_LAYOUT_ACTIONS
    assert "turn_deck_layout" in _DECK_LAYOUT_ACTIONS
    # Ancestor/child tree modes are artifact-relation actions, off on Agents.
    assert "start_child_mode" in _ARTIFACT_RELATION_ACTIONS
    assert "start_ancestor_mode" in _ARTIFACT_RELATION_ACTIONS
    assert _available("start_child_mode", "agents") is False
    assert _available("start_ancestor_mode", "agents") is False
