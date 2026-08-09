"""Keyboard-driven end-to-end coverage for clan cleanup."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
)


def _clan_member(
    name: str,
    suffix: str,
    *,
    clan: str,
    generation: str,
    tribe: str | None,
    status: str = "DONE",
    pid: int | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/projects/demo/demo.sase",
        status=status,
        start_time=datetime(2026, 7, 19, 8, 0, 0),
        stop_time=(datetime(2026, 7, 19, 8, 30, 0) if status == "DONE" else None),
        raw_suffix=suffix,
        agent_name=name,
        tribe=tribe,
        pid=pid,
        agent_clan=clan,
        agent_clan_generation=generation,
    )


async def test_clan_cleanup_keyboard_flow_partitions_and_updates_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha_running = _clan_member(
        "alpha.run",
        "alpha-run",
        clan="alpha",
        generation="alpha-generation",
        tribe="epic",
        status="RUNNING",
        pid=101,
    )
    alpha_done = _clan_member(
        "alpha.done",
        "alpha-done",
        clan="alpha",
        generation="alpha-generation",
        tribe="epic",
    )
    review_done = _clan_member(
        "review.done",
        "review-done",
        clan="review",
        generation="review-generation",
        tribe="review",
    )
    no_tribe_done = _clan_member(
        "no-tribe.done",
        "no-tribe-done",
        clan="no-tribe",
        generation="no-tribe-generation",
        tribe=None,
    )
    agents = [alpha_running, alpha_done, review_done, no_tribe_done]
    patch_startup_loaders(monkeypatch, agents=agents)

    killed: list[Agent] = []
    persistence_submissions: list[tuple[Any, ...]] = []

    def kill_process(_self: AceApp, agent: Agent) -> bool:
        killed.append(agent)
        return True

    monkeypatch.setattr(AceApp, "_kill_agent_process_group", kill_process)
    monkeypatch.setattr(
        AceApp,
        "_submit_bulk_kill_persistence_task",
        lambda _self, *args, **_kwargs: persistence_submissions.append(args),
    )

    async with AcePage(
        query='"demo"',
        patches=patches(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        assert page.app._panel_group.panel_keys == [None, "epic", "review"]

        await page.press("J")
        await page.wait_for(lambda _screen: page.app._panel_group.focused_key == "epic")

        initial_dismissed = set(page.app._dismissed_agents)
        page.app._marked_agents = {agent.identity for agent in agents}
        page.app._marked_agent_order = [agent.identity for agent in agents]
        notifications: list[tuple[str, str]] = []
        monkeypatch.setattr(
            page.app,
            "notify",
            lambda message, *, severity="information", **_kwargs: notifications.append(
                (message, severity)
            ),
        )

        await page.press("X")
        await page.expect_modal("AgentCleanupModal")
        await page.press("C")
        await page.expect_modal("AgentCleanupClanModal")
        await page.press("space", "enter")
        await page.expect_modal("ConfirmKillAllModal")

        confirm = page.app.screen
        description = confirm.agent_description
        assert "Clan: alpha" in description
        assert "Kill: 1 lane" in description
        assert "Dismiss: 1 lane" in description
        assert "alpha.run" in description
        assert "alpha.done" in description
        assert "review.done" not in description
        assert "no-tribe.done" not in description

        await page.press("y", "y")
        await page.expect_no_modal()
        await page.wait_for(
            lambda _screen: any(
                message == "Killed 1 agent and dismissed 1 agent"
                for message, _severity in notifications
            )
        )

        selected_ids = {alpha_running.identity, alpha_done.identity}
        untouched_ids = {review_done.identity, no_tribe_done.identity}
        assert {agent.identity for agent in killed} == {alpha_running.identity}
        assert page.app._dismissed_agents - initial_dismissed == selected_ids
        assert page.app._marked_agents == set()
        assert page.app._marked_agent_order == []
        assert selected_ids.isdisjoint(
            {agent.identity for agent in page.app._agents_with_children}
        )
        assert untouched_ids <= {
            agent.identity for agent in page.app._agents_with_children
        }

        assert len(persistence_submissions) == 1
        kill_items, dismissable, dismissed_snapshot, *_rest = persistence_submissions[0]
        assert {item.agent.identity for item in kill_items} == {alpha_running.identity}
        assert {agent.identity for agent in dismissable} == {alpha_done.identity}
        assert selected_ids <= dismissed_snapshot
