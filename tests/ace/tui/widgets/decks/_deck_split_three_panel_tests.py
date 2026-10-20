from __future__ import annotations

from pathlib import Path

from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckLayout
from tests.ace.tui.widgets.decks._deck_split_test_support import (
    DetailApp,
    make_artifact_agent,
    pin_paged,
)


async def test_three_panel_resize_clamps_to_minimums(tmp_path: Path) -> None:
    from sase.ace.tui.util.pane_grid import _main_pane

    app = DetailApp()
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
    app = DetailApp()
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
