"""Mounted-app coverage for the Agents grouping picker route."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.keymaps import build_app_bindings, load_keymap_registry
from sase.ace.tui.modals.agent_grouping_modal import AgentGroupingModal
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.widgets.agent_list import AgentList
from sase.core.time import local_now
from textual.binding import BindingsMap


def _agent(name: str, *, tribe: str | None, suffix: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file="/repo/project.sase",
        status="RUNNING",
        start_time=local_now(),
        agent_name=name,
        tribe=tribe,
        raw_suffix=suffix,
    )


async def _seed_multiple_tribe_agents(page: AcePage) -> None:
    agents = [
        _agent("home", tribe=None, suffix="20260101000000"),
        _agent("default-one", tribe="default", suffix="20260101000030"),
        _agent("alpha-one", tribe="alpha", suffix="20260101000100"),
        _agent("beta-one", tribe="beta", suffix="20260101000200"),
    ]
    page.app._agents = agents
    page.app._agents_with_children = list(agents)
    page.app.current_idx = 0
    page.app._agent_panels_grouped = False
    page.app._invalidate_agent_panel_cache()
    page.app._refresh_agents_display(list_changed=True)
    await page.pause()


def _install_keymap(page: AcePage, ace_cfg: dict) -> None:
    registry = load_keymap_registry(ace_cfg)
    page.app._keymap_registry = registry
    page.app._bindings = BindingsMap(build_app_bindings(registry.app))


def _agent_list_prompts(widget: AgentList) -> list[str]:
    return [
        widget.get_option_at_index(index).prompt.plain
        for index in range(widget.option_count)
    ]


async def test_agents_o_opens_picker_and_direct_choice_applies() -> None:
    async with AcePage(initial_tab="agents") as page:
        await page.press("o")
        await page.expect_modal("AgentGroupingModal")
        first_screen = page.app.screen

        page.app.action_choose_agent_grouping()
        await page.pause()
        assert page.app.screen is first_screen

        await page.press("m")
        await page.expect_no_modal()
        assert page.app._grouping_mode is GroupingMode.BY_MACHINE


async def test_agents_default_oo_toggles_panel_layout_once_and_preserves_mode() -> None:
    async with AcePage(initial_tab="agents") as page:
        await _seed_multiple_tribe_agents(page)
        initial_save_state = dict(page.app._grouping_mode_save_pending)

        assert page.app._panel_group.panel_keys == [None, "alpha", "beta"]
        assert page.app._grouping_mode is GroupingMode.STANDARD
        assert page.app._agent_panels_grouped is False

        await page.press("o", "o")
        await page.expect_no_modal()
        await page.wait_for(lambda _state: page.app._agent_panels_grouped is True)

        assert page.app._panel_group.panel_keys == [None]
        assert page.app._grouping_mode is GroupingMode.STANDARD
        assert page.app._grouping_mode_save_pending == initial_save_state
        merged_list = page.app.query_one("#agent-list-panel", AgentList)
        merged_prompts = "\n".join(_agent_list_prompts(merged_list))
        assert "@default" not in merged_prompts
        assert "@alpha" in merged_prompts
        assert "@beta" in merged_prompts

        await page.press("o", "o")
        await page.expect_no_modal()
        await page.wait_for(lambda _state: page.app._agent_panels_grouped is False)

        assert page.app._panel_group.panel_keys == [None, "alpha", "beta"]
        assert page.app._grouping_mode is GroupingMode.STANDARD
        assert page.app._grouping_mode_save_pending == initial_save_state


async def test_agents_rebound_opener_then_o_toggles_layout() -> None:
    async with AcePage(initial_tab="agents") as page:
        _install_keymap(page, {"keymaps": {"app": {"choose_agent_grouping": "f12"}}})

        await page.press("o")
        await page.pause()
        assert not isinstance(page.app.screen, AgentGroupingModal)
        assert page.app._agent_panels_grouped is False

        await page.press("f12")
        await page.expect_modal("AgentGroupingModal")
        await page.press("o")
        await page.expect_no_modal()

        assert page.app._agent_panels_grouped is True


async def test_agents_prompt_input_owns_o_key() -> None:
    async with AcePage(initial_tab="agents") as page:
        await page.press("space")
        await page.wait_for(lambda _state: page.app._prompt_input_active())

        await page.press("o")
        await page.pause()

        assert page.app._prompt_input_active()
        assert not isinstance(page.app.screen, AgentGroupingModal)
        assert page.app._agent_panels_grouped is False


async def test_agents_grouping_result_after_tab_change_is_ignored() -> None:
    async with AcePage(initial_tab="agents") as page:
        await page.press("o")
        await page.expect_modal("AgentGroupingModal")

        page.app.current_tab = "services"
        await page.press("o")
        await page.expect_no_modal()

        assert page.app._agent_panels_grouped is False


async def test_agents_default_capital_o_is_noop() -> None:
    async with AcePage(initial_tab="agents") as page:
        page.app._set_agents_grouping_mode(GroupingMode.STANDARD)
        await page.press("O")
        await page.pause()

        assert page.app._grouping_mode is GroupingMode.STANDARD
        assert not isinstance(page.app.screen, AgentGroupingModal)
