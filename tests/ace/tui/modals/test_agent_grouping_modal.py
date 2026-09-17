"""Behavioral coverage for the Agents grouping picker modal."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.modals.agent_grouping_modal import (
    AgentGroupingAction,
    AgentGroupingModal,
    AgentGroupingResult,
)
from sase.ace.tui.models.agent_groups import GroupingMode
from textual.widgets import Static


def _plain(modal: AgentGroupingModal, selector: str) -> str:
    return modal.query_one(selector, Static).render().plain


async def test_agent_grouping_modal_direct_keys_and_cancel() -> None:
    results: list[AgentGroupingResult] = []
    async with AcePage() as page:
        page.app.push_screen(AgentGroupingModal(GroupingMode.STANDARD), results.append)
        await page.expect_modal("AgentGroupingModal")

        await page.press("x", "O")
        await page.pause()
        assert page.state["modal"] == "AgentGroupingModal"
        assert results == []

        await page.press("s")
        await page.expect_no_modal()
        assert results == [GroupingMode.BY_STATUS]

        page.app.push_screen(AgentGroupingModal(GroupingMode.BY_STATUS), results.append)
        await page.expect_modal("AgentGroupingModal")
        await page.press("escape")
        await page.expect_no_modal()
        assert results == [GroupingMode.BY_STATUS, None]


async def test_agent_grouping_modal_navigation_enter_and_current_badge() -> None:
    results: list[AgentGroupingResult] = []
    async with AcePage() as page:
        modal = AgentGroupingModal(GroupingMode.BY_DATE)
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentGroupingModal")

        def row_focused(_screen: object) -> bool:
            rows = list(modal.query("#agent-grouping-row-1"))
            return bool(rows) and rows[0].has_class("focused")

        await page.wait_for(row_focused)

        assert modal.query_one("#agent-grouping-row-1").has_class("focused")
        assert modal.query_one("#agent-grouping-row-1").has_class("current")

        await page.press("j", "j")
        assert modal.query_one("#agent-grouping-row-3").has_class("focused")
        assert modal.query_one("#agent-grouping-row-1").has_class("current")

        await page.press("enter")
        await page.expect_no_modal()
        assert results == [GroupingMode.BY_MACHINE]


async def test_agent_grouping_modal_layout_labels_direct_key_and_cancel() -> None:
    results: list[AgentGroupingResult] = []
    async with AcePage() as page:
        split_modal = AgentGroupingModal(
            GroupingMode.STANDARD,
            current_panel_grouped=False,
        )
        page.app.push_screen(split_modal, results.append)
        await page.expect_modal("AgentGroupingModal")
        await page.wait_for(
            lambda _screen: bool(split_modal.query("#agent-panel-layout-row"))
        )

        split_text = _plain(split_modal, "#agent-panel-layout-row")
        assert "Merge panels" in split_text
        assert "Current: Split by tribe" in split_text

        await page.press("o")
        await page.expect_no_modal()
        split_modal.action_select_current()
        assert results == [AgentGroupingAction.TOGGLE_PANELS]

        merged_modal = AgentGroupingModal(
            GroupingMode.BY_STATUS,
            current_panel_grouped=True,
        )
        page.app.push_screen(merged_modal, results.append)
        await page.expect_modal("AgentGroupingModal")
        await page.wait_for(
            lambda _screen: bool(merged_modal.query("#agent-panel-layout-row"))
        )

        merged_text = _plain(merged_modal, "#agent-panel-layout-row")
        assert "Split panels by tribe" in merged_text
        assert "Current: Merged panel" in merged_text
        assert merged_modal.query_one("#agent-grouping-row-2").has_class("current")

        await page.press("escape")
        await page.expect_no_modal()
        assert results == [AgentGroupingAction.TOGGLE_PANELS, None]


async def test_agent_grouping_modal_layout_navigation_enter_and_click() -> None:
    results: list[AgentGroupingResult] = []
    async with AcePage(size=(50, 10)) as page:
        modal = AgentGroupingModal(GroupingMode.STANDARD)
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentGroupingModal")

        await page.press("j", "j", "j", "j")
        await page.wait_for(
            lambda _screen: modal.query_one("#agent-panel-layout-row").has_class(
                "focused"
            )
        )
        await page.press("enter")
        await page.expect_no_modal()
        modal.action_select_current()
        assert results == [AgentGroupingAction.TOGGLE_PANELS]

    async with AcePage() as page:
        page.app.push_screen(AgentGroupingModal(GroupingMode.STANDARD), results.append)
        await page.expect_modal("AgentGroupingModal")
        await page.wait_for(
            lambda _screen: bool(page.app.screen.query("#agent-panel-layout-row"))
        )
        await page.click("#agent-panel-layout-row")
        await page.expect_no_modal()

    assert results == [
        AgentGroupingAction.TOGGLE_PANELS,
        AgentGroupingAction.TOGGLE_PANELS,
    ]


async def test_agent_grouping_modal_click_selects_row() -> None:
    results: list[AgentGroupingResult] = []
    async with AcePage() as page:
        page.app.push_screen(AgentGroupingModal(GroupingMode.STANDARD), results.append)
        await page.expect_modal("AgentGroupingModal")
        await page.wait_for(
            lambda _screen: bool(page.app.screen.query("#agent-grouping-row-2"))
        )

        await page.click("#agent-grouping-row-2")
        await page.expect_no_modal()

    assert results == [GroupingMode.BY_STATUS]
