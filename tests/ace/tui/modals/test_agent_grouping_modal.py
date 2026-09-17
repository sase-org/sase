"""Behavioral coverage for the Agents grouping picker modal."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.modals.agent_grouping_modal import AgentGroupingModal
from sase.ace.tui.models.agent_groups import GroupingMode


async def test_agent_grouping_modal_direct_keys_and_cancel() -> None:
    results: list[GroupingMode | None] = []
    async with AcePage() as page:
        page.app.push_screen(AgentGroupingModal(GroupingMode.STANDARD), results.append)
        await page.expect_modal("AgentGroupingModal")

        await page.press("x", "o", "O")
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
    results: list[GroupingMode | None] = []
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


async def test_agent_grouping_modal_click_selects_row() -> None:
    results: list[GroupingMode | None] = []
    async with AcePage() as page:
        page.app.push_screen(AgentGroupingModal(GroupingMode.STANDARD), results.append)
        await page.expect_modal("AgentGroupingModal")
        await page.wait_for(
            lambda _screen: bool(page.app.screen.query("#agent-grouping-row-2"))
        )

        await page.click("#agent-grouping-row-2")
        await page.expect_no_modal()

    assert results == [GroupingMode.BY_STATUS]
