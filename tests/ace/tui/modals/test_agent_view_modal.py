"""Behavioral coverage for the Agents view picker modal."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.modals.agent_view_modal import (
    AgentViewChoice,
    AgentViewModal,
    AgentViewResult,
)
from sase.ace.tui.widgets._agent_detail_panels import (
    DetailLayoutMode,
    DetailPanelMode,
)


def _choices() -> tuple[AgentViewChoice, ...]:
    return (
        AgentViewChoice(
            "f",
            "File",
            "Files and diffs",
            "view",
            AgentViewResult.mode_choice(DetailPanelMode.AUTO),
            badge="Current",
        ),
        AgentViewChoice(
            "t",
            "Tools",
            "Unavailable for this entry",
            "view",
            AgentViewResult.mode_choice(DetailPanelMode.TOOLS),
            enabled=False,
            disabled_reason="Unavailable for this entry",
        ),
        AgentViewChoice(
            "n",
            "None",
            "Metadata fills the detail area",
            "view",
            AgentViewResult.mode_choice(DetailPanelMode.INFO),
        ),
        AgentViewChoice(
            "1",
            "Metadata larger",
            "Metadata 70% / File 30%",
            "layout",
            AgentViewResult.layout_choice(DetailLayoutMode.METADATA_LARGER),
        ),
        AgentViewChoice(
            "2",
            "File larger",
            "Metadata 30% / File 70%",
            "layout",
            AgentViewResult.layout_choice(DetailLayoutMode.SECONDARY_LARGER),
        ),
        AgentViewChoice(
            "p",
            "Swap sizes",
            "File larger -> Metadata larger",
            "layout",
            AgentViewResult.swap(),
        ),
    )


async def test_agent_view_modal_direct_keys_disabled_and_cancel() -> None:
    results: list[AgentViewResult | None] = []
    async with AcePage() as page:
        modal = AgentViewModal(_choices(), selected_key="f")
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentViewModal")

        await page.press("[", "]", "t")
        await page.pause()

        assert page.state["modal"] == "AgentViewModal"
        assert results == []
        assert modal.query_one("#agent-view-row-1").has_class("blocked")

        await page.press("escape")
        await page.expect_no_modal()
        assert results == [None]


async def test_agent_view_modal_navigation_skips_disabled_and_enter_selects() -> None:
    results: list[AgentViewResult | None] = []
    async with AcePage() as page:
        modal = AgentViewModal(_choices(), selected_key="f")
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentViewModal")
        await page.wait_for(lambda _screen: bool(modal.query("#agent-view-row-0")))

        await page.press("j")
        assert modal.query_one("#agent-view-row-2").has_class("focused")

        await page.press("enter")
        await page.expect_no_modal()
        assert results == [AgentViewResult.mode_choice(DetailPanelMode.INFO)]


async def test_agent_view_modal_click_selects_row() -> None:
    results: list[AgentViewResult | None] = []
    async with AcePage() as page:
        page.app.push_screen(
            AgentViewModal(_choices(), selected_key="f"),
            results.append,
        )
        await page.expect_modal("AgentViewModal")
        await page.wait_for(
            lambda _screen: bool(page.app.screen.query("#agent-view-row-3"))
        )

        await page.click("#agent-view-row-3")
        await page.expect_no_modal()

    assert results == [AgentViewResult.layout_choice(DetailLayoutMode.METADATA_LARGER)]
