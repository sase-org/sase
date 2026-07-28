"""ACE PNG regression for group-scoped uppercase-H clan collapse."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.keybinding_footer import KeybindingFooter
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _group_clan_agents() -> list[Agent]:
    project_file = "/workspace/sase/visual_project.sase"
    started = datetime(2026, 7, 22, 8, 0, 0)

    def agent(
        name: str,
        *,
        status: str,
        tribe: str | None,
        clan: str | None = None,
        minute: int = 0,
    ) -> Agent:
        return Agent(
            agent_type=AgentType.RUNNING,
            cl_name=name,
            project_file=project_file,
            status=status,
            start_time=started.replace(minute=minute),
            run_start_time=started.replace(minute=minute),
            raw_suffix=f"visual-{name}",
            agent_name=name,
            agent_clan=clan,
            agent_clan_generation="generation" if clan is not None else None,
            tribe=tribe,
            llm_provider="codex",
            model="gpt-5",
        )

    return [
        agent("home", status="DONE", tribe=None),
        agent(
            "sase-8k.plan",
            status="RUNNING",
            tribe="epic",
            clan="sase-8k",
            minute=1,
        ),
        agent(
            "sase-8k.code",
            status="WAITING",
            tribe="epic",
            clan="sase-8k",
            minute=2,
        ),
        agent(
            "sase-8l.plan",
            status="RUNNING",
            tribe="epic",
            clan="sase-8l",
            minute=3,
        ),
        agent("finished", status="DONE", tribe="epic", minute=4),
    ]


async def test_selected_clan_collapses_before_open_sibling_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 22, 9, 0, 0))
    patch_startup_loaders(monkeypatch, agents=_group_clan_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.press("o", "o")
        assert page.app._grouping_mode is GroupingMode.BY_STATUS

        clans = {
            agent.agent_clan: agent
            for agent in page.app._agents_with_children
            if agent.is_clan_container and agent.agent_clan in {"sase-8k", "sase-8l"}
        }
        selected_clan = clans["sase-8k"]
        sibling_clan = clans["sase-8l"]
        selected_key = agent_fold_key(selected_clan)
        sibling_key = agent_fold_key(sibling_clan)
        assert selected_key is not None and sibling_key is not None
        page.app._fold_manager.expand(selected_key)
        page.app._fold_manager.expand(sibling_key)
        page.app._refilter_agents(refresh_content_index=False)

        selected_member = next(
            agent for agent in page.app._agents if agent.cl_name == "sase-8k.plan"
        )
        page.app._panel_group.focused_idx = page.app._panel_group.panel_keys.index(
            "epic"
        )
        page.app._collapsed_panel_keys.discard("epic")
        page.app._expanded_panel_keys.add("epic")
        page.app._expanded_panel_focus = False
        page.app.current_idx = page.app._agents.index(selected_member)
        page.app._current_group_key = None
        page.app._refresh_agents_display(list_changed=True)
        await wait_for_visual_idle(page)

        footer = page.app.query_one("#keybinding-footer", KeybindingFooter)
        assert footer._last_layout_inputs is not None
        assert ("H", "collapse clan") in footer._last_layout_inputs[0]
        registry = page.app._group_fold_registry.for_panel("epic")
        assert page.app._fold_manager.get(selected_key) is FoldLevel.EXPANDED
        assert page.app._fold_manager.get(sibling_key) is FoldLevel.EXPANDED
        assert not registry.is_collapsed(("Running",))

        await page.press("H")
        await wait_for_visual_idle(page)

        selected = page.app._agents[page.app.current_idx]
        assert selected.identity == selected_clan.identity
        assert page.app._fold_manager.get(selected_key) is FoldLevel.COLLAPSED
        assert page.app._fold_manager.get(sibling_key) is FoldLevel.EXPANDED
        assert not registry.is_collapsed(("Running",))
        assert footer._last_layout_inputs is not None
        assert ("H", "collapse clans") in footer._last_layout_inputs[0]
        ace_png_visual.assert_page_png(
            page,
            "agents_selected_clan_collapse_precedence_120x40",
            title="ACE selected clan collapse before sibling clans",
        )


async def test_group_clan_collapse_precedes_status_banner_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 22, 9, 0, 0))
    patch_startup_loaders(monkeypatch, agents=_group_clan_agents())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.press("o", "o")
        assert page.app._grouping_mode is GroupingMode.BY_STATUS

        clans = {
            agent.agent_clan: agent
            for agent in page.app._agents_with_children
            if agent.is_clan_container and agent.agent_clan in {"sase-8k", "sase-8l"}
        }
        open_clan = clans["sase-8k"]
        selected_clan = clans["sase-8l"]
        open_key = agent_fold_key(open_clan)
        selected_key = agent_fold_key(selected_clan)
        assert open_key is not None and selected_key is not None
        page.app._fold_manager.expand(open_key)
        page.app._refilter_agents(refresh_content_index=False)

        selected_clan = next(
            agent
            for agent in page.app._agents
            if agent.is_clan_container and agent.agent_clan == "sase-8l"
        )
        selected_identity = selected_clan.identity
        page.app._panel_group.focused_idx = page.app._panel_group.panel_keys.index(
            "epic"
        )
        page.app._collapsed_panel_keys.discard("epic")
        page.app._expanded_panel_keys.add("epic")
        page.app._expanded_panel_focus = False
        page.app.current_idx = page.app._agents.index(selected_clan)
        page.app._current_group_key = None
        page.app._refresh_agents_display(list_changed=True)
        await wait_for_visual_idle(page)

        footer = page.app.query_one("#keybinding-footer", KeybindingFooter)
        assert footer._last_layout_inputs is not None
        assert ("H", "collapse clans") in footer._last_layout_inputs[0]
        registry = page.app._group_fold_registry.for_panel("epic")
        assert page.app._fold_manager.get(open_key) is FoldLevel.EXPANDED
        assert page.app._fold_manager.get(selected_key) is FoldLevel.COLLAPSED
        assert not registry.is_collapsed(("Running",))

        await page.press("H")
        await wait_for_visual_idle(page)

        assert page.app._agents[page.app.current_idx].identity == selected_identity
        assert page.app._fold_manager.get(open_key) is FoldLevel.COLLAPSED
        assert page.app._fold_manager.get(selected_key) is FoldLevel.COLLAPSED
        assert not registry.is_collapsed(("Running",))
        assert footer._last_layout_inputs is not None
        assert ("H", "collapse group") in footer._last_layout_inputs[0]
        ace_png_visual.assert_page_png(
            page,
            "agents_group_clan_collapse_precedence_120x40",
            title="ACE group-wide clan collapse before status banner",
        )

        await page.press("H")
        await wait_for_visual_idle(page)
        assert registry.is_collapsed(("Running",))
