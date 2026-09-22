"""Keyboard-driven sticky-panel retirement for emptied clan tribe panels.

A folded clan's synthetic container is the only rendered row keeping its
tribe panel mounted. Dismissing or killing the clan's last members through
the cleanup panel must unmount the tribe widget on the keypress instead of
leaving an empty ``@tribe · 0`` strip behind.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.actions.agents._clan_cleanup import clan_members_for_container
from sase.ace.tui.actions.agents._display_helpers import panel_widget_id_for_key
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import AgentList
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
)


def _clan_member(
    name: str,
    suffix: str,
    *,
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
        tribe="epic",
        pid=pid,
        agent_clan="alpha",
        agent_clan_generation="alpha-generation",
    )


def _home_agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="home",
        project_file="/tmp/projects/demo/demo.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 19, 8, 0, 0),
        raw_suffix="home",
        agent_name="home",
        tribe=None,
        pid=101,
    )


def _container_identities(app: AceApp) -> set[tuple[AgentType, str, str | None]]:
    return {
        agent.identity
        for agent in (*app._agents, *app._agents_with_children)
        if agent.is_clan_container
    }


async def _focus_epic_panel(page: AcePage) -> None:
    """Focus the ``@epic`` panel, moving off ``@default`` when needed."""
    if page.app._panel_group.focused_key != "epic":
        await page.press("J")
        await page.wait_for(lambda _screen: page.app._panel_group.focused_key == "epic")


async def test_cleanup_dismiss_folded_clan_unmounts_its_tribe_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``X d y`` on a folded clan's last DONE members retires ``@epic``."""
    first = _clan_member("alpha.one", "alpha-one")
    second = _clan_member("alpha.two", "alpha-two")
    home = _home_agent()
    patch_startup_loaders(monkeypatch, agents=[first, second, home])

    async with AcePage(
        query='"demo"',
        patches=patches(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        assert page.app._panel_group.panel_keys == [None, "epic"]
        # Folded: the synthetic container is the only rendered epic row.
        assert {a.identity for a in page.app._agents} == {
            home.identity,
            next(
                a.identity
                for a in page.app._agents_with_children
                if a.is_clan_container
            ),
        }

        await _focus_epic_panel(page)

        await page.press("X")
        await page.expect_modal("AgentCleanupModal")
        await page.press("d")
        await page.expect_modal("ConfirmDismissAllModal")
        await page.press("y")
        await page.expect_no_modal()
        await page.wait_for(
            lambda _screen: first.identity in page.app._dismissed_agents
        )
        await page.wait_for(lambda _screen: page.app._panel_group.panel_keys == [None])

        assert "epic" not in page.app._session_mounted_panel_key_set()
        epic_widget_id = panel_widget_id_for_key("epic")
        await page.wait_for(
            lambda _screen: (
                epic_widget_id
                not in {widget.id for widget in page.app.query(AgentList)}
            )
        )
        assert _container_identities(page.app) == set()


async def test_cleanup_kill_folded_clan_unmounts_its_tribe_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``X k y y`` on a folded clan's last RUNNING member retires ``@epic``."""
    member = _clan_member("alpha.one", "alpha-one", status="RUNNING", pid=102)
    home = _home_agent()
    patch_startup_loaders(monkeypatch, agents=[member, home])
    killed: list[Agent] = []
    persistence_submissions: list[tuple[object, ...]] = []

    def kill_process(_self: AceApp, agent: Agent) -> bool:
        killed.append(agent)
        return True

    monkeypatch.setattr(AceApp, "_kill_agent_process_group", kill_process)
    monkeypatch.setattr(
        AceApp,
        "_submit_bulk_kill_persistence_proc",
        lambda _self, *args, **_kwargs: persistence_submissions.append(args),
    )

    async with AcePage(
        query='"demo"',
        patches=patches(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        assert page.app._panel_group.panel_keys == [None, "epic"]

        await _focus_epic_panel(page)

        await page.press("X")
        await page.expect_modal("AgentCleanupModal")
        await page.press("k")
        await page.expect_modal("ConfirmKillAllModal")
        await page.press("y", "y")
        await page.expect_no_modal()
        await page.wait_for(
            lambda _screen: member.identity in page.app._dismissed_agents
        )
        await page.wait_for(lambda _screen: page.app._panel_group.panel_keys == [None])

        assert {agent.identity for agent in killed} == {member.identity}
        assert "epic" not in page.app._session_mounted_panel_key_set()
        epic_widget_id = panel_widget_id_for_key("epic")
        await page.wait_for(
            lambda _screen: (
                epic_widget_id
                not in {widget.id for widget in page.app.query(AgentList)}
            )
        )
        assert _container_identities(page.app) == set()


async def test_cleanup_dismiss_partial_clan_keeps_panel_and_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dismissing one of two clan members keeps ``@epic`` and its container."""
    done = _clan_member("alpha.done", "alpha-done")
    running = _clan_member("alpha.running", "alpha-running", status="RUNNING", pid=103)
    home = _home_agent()
    patch_startup_loaders(monkeypatch, agents=[done, running, home])

    async with AcePage(
        query='"demo"',
        patches=patches(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        assert page.app._panel_group.panel_keys == [None, "epic"]

        await _focus_epic_panel(page)

        await page.press("X")
        await page.expect_modal("AgentCleanupModal")
        await page.press("d")
        await page.expect_modal("ConfirmDismissAllModal")
        await page.press("y")
        await page.expect_no_modal()
        await page.wait_for(lambda _screen: done.identity in page.app._dismissed_agents)
        await page.wait_for(
            lambda _screen: (
                done.identity
                not in {agent.identity for agent in page.app._agents_with_children}
            )
        )

        assert "epic" in page.app._session_mounted_panel_key_set()
        assert page.app._panel_group.panel_keys == [None, "epic"]
        containers = [agent for agent in page.app._agents if agent.is_clan_container]
        assert len(containers) == 1
        assert {
            member.identity
            for member in clan_members_for_container(
                containers[0], page.app._agents_with_children
            )
        } == {running.identity}
