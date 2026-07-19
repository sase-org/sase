"""Collapsed whole-panel kill/dismiss action coverage."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.actions.agents._kill_action import AgentKillMixin
from sase.ace.tui.actions.agents._marking import AgentMarkingMixin
from sase.ace.tui.actions.agents._selection import AgentSelectionMixin
from sase.ace.tui.modals import ConfirmDismissAllModal, ConfirmKillAllModal
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panel_index import build_agent_panel_index
from sase.ace.tui.models.agent_tribe_summary import CollapsedAgentPanelFocus
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
)


def _agent(
    name: str,
    suffix: str,
    *,
    tribe: str | None = "chop",
    status: str = "RUNNING",
    pid: int | None = 100,
    agent_type: AgentType = AgentType.RUNNING,
    workflow: str | None = None,
    parent_timestamp: str | None = None,
    parent_workflow: str | None = None,
    agent_clan: str | None = None,
    agent_clan_generation: str | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=name,
        project_file="/tmp/projects/demo/demo.sase",
        status=status,
        start_time=datetime(2026, 7, 18, 9, 0, 0),
        raw_suffix=suffix,
        tribe=tribe,
        pid=pid,
        workflow=workflow,
        parent_timestamp=parent_timestamp,
        parent_workflow=parent_workflow,
        agent_clan=agent_clan,
        agent_clan_generation=agent_clan_generation,
    )


class _CollapsedPanelKillApp(
    AgentKillMixin,
    AgentMarkingMixin,
    AgentSelectionMixin,
):
    current_tab: Any

    def __init__(
        self,
        agents: list[Agent],
        *,
        focused_key: str | None = "chop",
        agents_with_children: list[Agent] | None = None,
    ) -> None:
        self.current_tab = "agents"
        self._agents = list(agents)
        self._agents_with_children = list(
            agents if agents_with_children is None else agents_with_children
        )
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self._marked_agent_order: list[tuple[AgentType, str, str | None]] = []
        self._current_group_key: tuple[str, ...] | None = None
        self._collapsed_panel_keys = {focused_key}
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            focused_key=focused_key,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )
        self._index = build_agent_panel_index(
            self._agents,
            dismissable_statuses={"DONE", "FAILED", "PLAN DONE", "TALE DONE"},
        )
        focused_indices = self._index.slice_for(focused_key).global_indices
        self.current_idx = focused_indices[0] if focused_indices else 0
        self.notifications: list[tuple[str, str]] = []
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []

    def _agent_panel_index(self):  # type: ignore[no-untyped-def]
        return self._index

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed_modals.append(modal)
        self.pushed_callbacks.append(callback)

    def _do_bulk_kill_agents(
        self, killable: list[Agent], dismissable: list[Agent] | None = None
    ) -> None:
        del killable, dismissable


def test_collapsed_tribe_assigned_panel_partitions_complete_scope_and_confirms_once() -> (
    None
):
    running = _agent("running", "run", pid=101)
    done = _agent("done", "done", status="DONE", pid=None)
    pidless = _agent("pidless", "pidless", pid=None)
    other = _agent("neighbor", "other", tribe="keep", pid=202)
    app = _CollapsedPanelKillApp([running, done, pidless, other])

    with patch.object(app, "_do_bulk_kill_agents") as bulk:
        app.action_kill_agent()

        assert isinstance(app.pushed_modals[0], ConfirmKillAllModal)
        description = app.pushed_modals[0].agent_description
        assert "Panel: @chop (3 agents)" in description
        assert "Kill: 1 running agent" in description
        assert "Dismiss: 2 agents" in description
        assert "running" in description
        assert "done" in description
        assert "pidless" in description
        assert "neighbor" not in description

        app.pushed_callbacks[0](True)

    bulk.assert_called_once_with([running], [done, pidless])


def test_collapsed_panel_cancel_has_no_mutation_boundary() -> None:
    running = _agent("running", "run")
    app = _CollapsedPanelKillApp([running])

    with patch.object(app, "_do_bulk_kill_agents") as bulk:
        app.action_kill_agent()
        app.pushed_callbacks[0](False)

    bulk.assert_not_called()


def test_expanded_panel_focus_uses_the_same_bulk_cleanup_scope() -> None:
    running = _agent("running", "run")
    neighbor = _agent("neighbor", "neighbor", tribe="keep")
    app = _CollapsedPanelKillApp([running, neighbor])
    app._collapsed_panel_keys.clear()
    app._expanded_panel_focus = True

    with patch.object(app, "_do_bulk_kill_agents") as bulk:
        app.action_kill_agent()
        assert isinstance(app.pushed_modals[0], ConfirmKillAllModal)
        description = app.pushed_modals[0].agent_description
        assert "Panel: @chop (1 agent)" in description
        assert "running" in description
        assert "neighbor" not in description
        app.pushed_callbacks[0](True)

    bulk.assert_called_once_with([running], [])


def test_no_tribe_pidless_panel_uses_dismiss_confirmation() -> None:
    done = _agent("done", "done", tribe=None, status="DONE", pid=None)
    pidless = _agent("pidless", "pidless", tribe=None, pid=None)
    tribe_assigned = _agent("tribe_assigned", "tribe_assigned", tribe="keep")
    app = _CollapsedPanelKillApp(
        [done, pidless, tribe_assigned],
        focused_key=None,
    )

    with patch.object(app, "_do_bulk_kill_agents") as bulk:
        app.action_kill_agent()
        assert isinstance(app.pushed_modals[0], ConfirmDismissAllModal)
        description = app.pushed_modals[0].agent_description
        assert "Panel: (no tribe) (2 agents)" in description
        assert "  tribe_assigned" not in description
        app.pushed_callbacks[0](True)

    bulk.assert_called_once_with([], [done, pidless])


def test_marks_take_priority_over_collapsed_panel_focus() -> None:
    marked = _agent("marked", "marked", tribe="keep")
    panel_agent = _agent("panel", "panel")
    app = _CollapsedPanelKillApp([marked, panel_agent])
    app._marked_agents = {marked.identity}

    with patch.object(app, "_bulk_kill_marked_agents") as marked_cleanup:
        app.action_kill_agent()

    marked_cleanup.assert_called_once_with()
    assert app.pushed_modals == []


def test_collapsed_panel_expands_clan_members_without_duplicates() -> None:
    running = _agent(
        "research.one",
        "one",
        agent_clan="research",
        agent_clan_generation="g1",
    )
    done = _agent(
        "research.two",
        "two",
        status="DONE",
        pid=None,
        agent_clan="research",
        agent_clan_generation="g1",
    )
    other = _agent("other", "other", tribe="keep")
    projected = project_clan_tree([running, done, other])
    app = _CollapsedPanelKillApp(projected)

    with patch.object(app, "_do_bulk_kill_agents") as bulk:
        app.action_kill_agent()
        description = app.pushed_modals[0].agent_description
        assert "Panel: @chop (2 agents)" in description
        assert description.count("research.one") == 1
        assert description.count("research.two") == 1
        assert "other" not in description
        app.pushed_callbacks[0](True)

    bulk.assert_called_once_with([running], [done])


def test_collapsed_panel_adds_loaded_workflow_children_but_not_neighbors() -> None:
    parent = _agent(
        "workflow-parent",
        "parent",
        agent_type=AgentType.WORKFLOW,
        workflow="demo-flow",
    )
    child = _agent(
        "workflow-child",
        "child",
        tribe=None,
        parent_timestamp="parent",
        parent_workflow="demo-flow",
    )
    neighbor = _agent("neighbor", "neighbor", tribe="keep")
    unrelated_child = _agent(
        "unrelated-child",
        "unrelated-child",
        tribe=None,
        parent_timestamp="neighbor",
        parent_workflow="other-flow",
    )
    app = _CollapsedPanelKillApp(
        [parent, neighbor],
        agents_with_children=[parent, child, neighbor, unrelated_child],
    )

    with patch.object(app, "_do_bulk_kill_agents") as bulk:
        app.action_kill_agent()
        description = app.pushed_modals[0].agent_description
        assert "Panel: @chop (2 agents)" in description
        assert "demo-flow" in description
        assert "workflow-child" in description
        assert "neighbor" not in description
        assert "unrelated-child" not in description
        app.pushed_callbacks[0](True)

    bulk.assert_called_once_with([parent, child], [])


def test_empty_or_stale_collapsed_focus_warns_without_modal() -> None:
    agent = _agent("agent", "agent")
    app = _CollapsedPanelKillApp([agent])
    app._index = build_agent_panel_index([], dismissable_statuses={"DONE"})

    app.action_kill_agent()

    assert app.pushed_modals == []
    assert app.notifications == [("No agents remain in collapsed panel", "warning")]

    app = _CollapsedPanelKillApp([agent])
    focus = CollapsedAgentPanelFocus(panel_key="chop")
    with patch.object(
        app,
        "_resolve_focused_collapsed_panel",
        side_effect=[focus, None],
    ):
        app.action_kill_agent()

    assert app.pushed_modals == []
    assert app.notifications == [
        ("Collapsed panel focus changed; nothing cleaned up", "warning")
    ]


async def test_confirming_last_panel_member_preserves_neighbors_and_valid_focus(
    monkeypatch: Any,
) -> None:
    home = _agent("home", "home", tribe=None, status="DONE", pid=None)
    chop = _agent("chop", "chop", status="DONE", pid=None)
    keep = _agent("keep", "keep", tribe="keep", status="DONE", pid=None)
    patch_startup_loaders(monkeypatch, agents=[home, chop, keep])
    persistence_submissions: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        AceApp,
        "_submit_bulk_kill_persistence_task",
        lambda _self, *args, **_kwargs: persistence_submissions.append(args),
    )

    async with AcePage(query='"demo"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.press("J")
        assert page.app._panel_group.focused_key == "chop"
        await page.press("h")
        await page.wait_for(
            lambda _screen: page.app._resolve_focused_panel() is not None
        )
        await page.press("h")
        await page.wait_for(lambda _screen: "chop" in page.app._collapsed_panel_keys)

        await page.press("x")
        await page.expect_modal("ConfirmDismissAllModal")
        await page.press("y")
        await page.expect_no_modal()
        assert chop.identity not in {agent.identity for agent in page.app._agents}
        await page.wait_for(
            lambda _screen: "chop" not in page.app._panel_group.panel_keys
        )

        assert {agent.identity for agent in page.app._agents} == {
            home.identity,
            keep.identity,
        }
        assert "chop" not in page.app._collapsed_panel_keys
        assert page.app._panel_group.focused_key in {None, "keep"}
        selected = page.app._get_selected_agent()
        assert selected is not None
        assert selected.identity in {home.identity, keep.identity}

    assert len(persistence_submissions) == 1
