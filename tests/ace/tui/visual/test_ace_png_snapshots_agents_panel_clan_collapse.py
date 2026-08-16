"""ACE PNG regression for selected-panel uppercase-H clan collapse."""

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
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _panel_clan_agents() -> list[Agent]:
    started = datetime(2026, 7, 22, 8, 0, 0)

    def agent(
        name: str,
        *,
        status: str,
        tribe: str | None,
        clan: str | None = None,
    ) -> Agent:
        return Agent(
            agent_type=AgentType.RUNNING,
            cl_name=name,
            project_file="/workspace/sase/visual_project.sase",
            status=status,
            start_time=started,
            run_start_time=started,
            raw_suffix=f"visual-{name}",
            agent_name=name,
            agent_clan=clan,
            agent_clan_generation="generation" if clan is not None else None,
            tribe=tribe,
        )

    return [
        agent("home", status="DONE", tribe=None),
        agent("toobig-g.plan", status="RUNNING", tribe="chop", clan="toobig-g"),
        agent("toobig-g.code", status="WAITING", tribe="chop", clan="toobig-g"),
        agent("finished", status="DONE", tribe="chop"),
    ]


async def test_selected_panel_clan_collapse_precedes_status_group_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 22, 9, 0, 0))
    patch_startup_loaders(monkeypatch, agents=_panel_clan_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.press("B", "B")
        assert page.app._grouping_mode is GroupingMode.BY_STATUS

        clan = next(
            agent
            for agent in page.app._agents_with_children
            if agent.is_clan_container and agent.agent_clan == "toobig-g"
        )
        clan_key = agent_fold_key(clan)
        assert clan_key is not None
        page.app._fold_manager.expand(clan_key)
        page.app._refilter_agents(refresh_content_index=False)
        clan = next(
            agent
            for agent in page.app._agents
            if agent.is_clan_container and agent.agent_clan == "toobig-g"
        )
        page.app._panel_group.focused_idx = page.app._panel_group.panel_keys.index(
            "chop"
        )
        page.app._collapsed_panel_keys.discard("chop")
        page.app._expanded_panel_keys.add("chop")
        page.app._expanded_panel_focus = False
        page.app.current_idx = page.app._agents.index(clan)
        page.app._current_group_key = None
        page.app._refresh_agents_display(list_changed=True)
        assert page.app._resolve_focused_panel() is None
        await page.press("h")
        await page.wait_for(
            lambda _screen: page.app._resolve_focused_panel() is not None
        )
        await wait_for_visual_idle(page)

        footer = page.app.query_one("#keybinding-footer", KeybindingFooter)
        assert footer._last_layout_inputs is not None
        assert ("H", "collapse fold") in footer._last_layout_inputs[0]
        registry = page.app._group_fold_registry.for_panel("chop")
        assert not registry.is_collapsed(("Running",))
        assert not registry.is_collapsed(("Done",))
        assert page.app._fold_manager.get(clan_key) is FoldLevel.EXPANDED
        ace_png_visual.assert_page_png(
            page,
            "agents_selected_panel_clan_collapse_120x40",
            title="ACE selected panel clan collapse",
        )

        await page.press("H")
        await page.wait_for(lambda _screen: page.app._panel_fold_hint_mode_active)
        fold_hints = page.app._panel_fold_target_to_hint
        clan_target = next(
            target
            for target in fold_hints
            if target[0] == "agent" and target[3] == clan_key
        )
        await page.press(fold_hints[clan_target])
        await page.wait_for(lambda _screen: not page.app._panel_fold_hint_mode_active)
        await wait_for_visual_idle(page)

        assert page.app._fold_manager.get(clan_key) is FoldLevel.COLLAPSED
        assert not registry.is_collapsed(("Running",))
        assert not registry.is_collapsed(("Done",))
        assert footer._last_layout_inputs is not None
        assert ("H", "collapse fold") in footer._last_layout_inputs[0]
