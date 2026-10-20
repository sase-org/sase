from __future__ import annotations

from pathlib import Path

import pytest
from sase.ace.tui.widgets.agent_detail import AgentDetail
from tests.ace.tui.widgets.decks._deck_split_test_support import (
    DeckKeyApp,
    make_artifact_agent,
    pin_paged,
)


async def test_real_deck_keys_reach_actions_on_two_and_three_panels(
    tmp_path: Path,
) -> None:
    app = DeckKeyApp()
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


@pytest.mark.parametrize(
    ("first_key", "second_key"),
    (("backslash", "vertical_line"), ("vertical_line", "backslash")),
)
async def test_real_split_keys_keep_focus_on_original_widget(
    tmp_path: Path, first_key: str, second_key: str
) -> None:
    app = DeckKeyApp()
    pin_paged(app)
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.update_display(make_artifact_agent(tmp_path, status="DONE"))
        await pilot.pause()
        area = detail.deck_area
        original = area.focused_panel()

        await pilot.press(first_key)
        await pilot.pause()
        assert len(area.state.grid.panes) == 2
        assert area.state.focused == 0
        assert area.focused_panel() is original
        assert original.has_class("-focused")
        assert all(
            panel.has_class("-unfocused")
            for panel in area.visible_panels()
            if panel is not original
        )

        await pilot.press(second_key)
        await pilot.pause()
        assert len(area.state.grid.panes) == 3
        assert area.state.focused == 0
        assert area.focused_panel() is original
        assert original.has_class("-focused")
        assert all(
            panel.has_class("-unfocused")
            for panel in area.visible_panels()
            if panel is not original
        )


async def test_deck_swap_keeps_identity_and_click_focuses_after_swap(
    tmp_path: Path,
) -> None:
    app = DeckKeyApp()
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
    app = DeckKeyApp()
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

    app = DeckKeyApp()
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
    app = DeckKeyApp()
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
