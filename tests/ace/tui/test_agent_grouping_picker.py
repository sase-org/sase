"""Mounted-app coverage for the Agents grouping picker route."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.modals.agent_grouping_modal import AgentGroupingModal
from sase.ace.tui.models.agent_groups import GroupingMode


async def test_agents_o_opens_picker_and_direct_choice_applies() -> None:
    async with AcePage(initial_tab="agents") as page:
        await page.press("o")
        await page.expect_modal("AgentGroupingModal")
        first_screen = page.app.screen

        await page.press("o")
        await page.pause()
        assert page.app.screen is first_screen

        await page.press("m")
        await page.expect_no_modal()
        assert page.app._grouping_mode is GroupingMode.BY_MACHINE


async def test_agents_default_capital_o_is_noop() -> None:
    async with AcePage(initial_tab="agents") as page:
        page.app._set_agents_grouping_mode(GroupingMode.STANDARD)
        await page.press("O")
        await page.pause()

        assert page.app._grouping_mode is GroupingMode.STANDARD
        assert not isinstance(page.app.screen, AgentGroupingModal)
