"""Mounted-app coverage for the Agents deck picker route."""

from __future__ import annotations

from textual.widgets import Static

from sase.ace.testing import AcePage, set_agent_prompt_document
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.modals.deck_picker_modal import DeckPickerModal
from sase.ace.tui.widgets import AgentDetail
from sase.ace.tui.widgets.decks.model import DeckId
from sase.core.time import local_now


def _agent(name: str, suffix: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file="/repo/project.sase",
        status="RUNNING",
        start_time=local_now(),
        agent_name=name,
        raw_suffix=suffix,
    )


async def _seed_agents(page: AcePage) -> None:
    agents = [
        _agent("home", "20260101000000"),
        _agent("second", "20260101000100"),
    ]
    page.app._agents = agents
    page.app._agents_with_children = list(agents)
    page.app.current_idx = 0
    page.app._invalidate_agent_panel_cache()
    page.app._refresh_agents_display(list_changed=True)
    await page.pause()


def _detail(page: AcePage) -> AgentDetail:
    return page.app.query_one("#agent-detail-panel", AgentDetail)


def _plain(page: AcePage, selector: str) -> str:
    modal = page.app.screen
    assert isinstance(modal, DeckPickerModal)
    return modal.query_one(selector, Static).render().plain


async def test_agents_p_opens_picker_and_f_switches_deck() -> None:
    async with AcePage(initial_tab="agents") as page:
        await _seed_agents(page)
        detail = _detail(page)
        assert detail.deck_area.panel(0).deck is DeckId.MAIN

        calls: list[None] = []
        original = page.app._agents_deck_state_changed
        page.app._agents_deck_state_changed = lambda: calls.append(None)  # type: ignore[method-assign]
        try:
            await page.press("p")
            await page.expect_modal("DeckPickerModal")

            await page.press("f")
            await page.expect_no_modal()
        finally:
            page.app._agents_deck_state_changed = original  # type: ignore[method-assign]
        assert detail.deck_area.panel(0).deck is DeckId.FILES
        assert calls, "switching decks schedules the deck-state save"


async def test_agents_pp_closes_picker_without_change() -> None:
    async with AcePage(initial_tab="agents") as page:
        await _seed_agents(page)
        detail = _detail(page)

        await page.press("p")
        await page.expect_modal("DeckPickerModal")
        await page.press("p")
        await page.expect_no_modal()
        assert detail.deck_area.panel(0).deck is DeckId.MAIN


async def test_agents_picking_current_deck_changes_nothing() -> None:
    async with AcePage(initial_tab="agents") as page:
        await _seed_agents(page)
        detail = _detail(page)

        await page.press("p")
        await page.expect_modal("DeckPickerModal")
        await page.press("m")
        await page.expect_no_modal()
        assert detail.deck_area.panel(0).deck is DeckId.MAIN


async def test_agents_picker_acts_on_focused_split_panel() -> None:
    async with AcePage(initial_tab="agents") as page:
        await _seed_agents(page)
        detail = _detail(page)

        await page.press("p")
        await page.expect_modal("DeckPickerModal")
        await page.press("f")
        await page.expect_no_modal()
        assert detail.deck_area.panel(0).deck is DeckId.FILES

        await page.press("backslash")
        await page.pause()
        assert detail.deck_area.state.focused == 1

        await page.press("p")
        await page.expect_modal("DeckPickerModal")
        assert _plain(page, "#deck-picker-heading") == (
            "Choose what the bottom panel shows"
        )
        assert "in top panel" in _plain(page, "#deck-picker-row-1")

        await page.press("t")
        await page.expect_no_modal()
        assert detail.deck_area.panel(0).deck is DeckId.FILES
        assert detail.deck_area.panel(1).deck is DeckId.TOOLS


async def test_agents_palette_show_deck_tools_command() -> None:
    async with AcePage(initial_tab="agents") as page:
        await _seed_agents(page)
        detail = _detail(page)

        page.app.action_show_deck_at(2)
        await page.pause()
        assert detail.deck_area.panel(0).deck is DeckId.TOOLS


async def test_agents_picker_does_not_stack_modals() -> None:
    async with AcePage(initial_tab="agents") as page:
        await _seed_agents(page)

        await page.press("p")
        await page.expect_modal("DeckPickerModal")
        first_screen = page.app.screen

        page.app.action_pick_deck()
        await page.pause()
        assert page.app.screen is first_screen

        await page.press("escape")
        await page.expect_no_modal()


async def test_agents_p_on_artifacts_tab_is_not_the_picker() -> None:
    async with AcePage(initial_tab="agents") as page:
        await _seed_agents(page)
        detail = _detail(page)

        page.app.current_tab = "artifacts"
        await page.pause()
        page.app.action_pick_deck()
        await page.pause()
        assert not isinstance(page.app.screen, DeckPickerModal)
        assert detail.deck_area.panel(0).deck is DeckId.MAIN


async def test_agents_prompt_input_owns_p_key() -> None:
    from sase.ace.tui._app_action_availability import check_app_action

    async with AcePage(initial_tab="agents") as page:
        await _seed_agents(page)
        original = page.app._prompt_input_active
        page.app._prompt_input_active = lambda: True  # type: ignore[method-assign]
        try:
            assert (
                check_app_action(page.app, "pick_deck", (), lambda _a, _p: True)
                is False
            )
            await page.press("p")
            await page.pause()
            assert not isinstance(page.app.screen, DeckPickerModal)
        finally:
            page.app._prompt_input_active = original  # type: ignore[method-assign]


async def test_agents_p_during_committed_search_exits_and_opens_picker() -> None:
    async with AcePage(initial_tab="agents") as page:
        await _seed_agents(page)
        await set_agent_prompt_document(
            page,
            "Alpha needle result\nSecond needle result\n"
            + "\n".join(f"filler line {index}" for index in range(80)),
        )

        await page.press("comma", "slash", "n", "e", "e", "d", "l", "e", "enter")
        await page.pause()
        assert page.app._agent_metadata_search.mode == "committed"

        await page.press("p")
        await page.expect_modal("DeckPickerModal")
        assert page.app._agent_metadata_search.mode == "off"

        await page.press("escape")
        await page.expect_no_modal()
