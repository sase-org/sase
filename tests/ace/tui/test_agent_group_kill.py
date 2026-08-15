"""Phase-5 tests for bulk kill/dismiss on collapsed group rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._kill_action import AgentKillMixin
from sase.ace.tui.actions.agents._marking import AgentMarkingMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import AgentPanelGroup


def _make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for group-kill tests."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "fix-bug",
        "project_file": "/tmp/projects/proj_a/proj_a.sase",
        "status": "RUNNING",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": "20240101120000",
        "pid": 4242,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class _FakeGroupKillApp(AgentKillMixin, AgentMarkingMixin):
    """Minimal app for testing the group-bulk-kill path."""

    current_tab: Any  # mixin declares a Literal — relax for the test stub.

    def __init__(self, agents: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents: list[Agent] = list(agents)
        self._agents_with_children: list[Agent] = list(agents)
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self._current_group_key: tuple[str, ...] | None = None
        self._group_fold_registry = AgentGroupFoldRegistry()
        self.notifications: list[tuple[str, str]] = []
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed_modals.append(modal)
        self.pushed_callbacks.append(callback)

    def _do_bulk_kill_agents(
        self, killable: list[Agent], dismissable: list[Agent] | None = None
    ) -> None:
        ids = {a.identity for a in killable}
        ids.update(a.identity for a in dismissable or [])
        self._agents = [a for a in self._agents if a.identity not in ids]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity not in ids
        ]

    def _dismiss_done_agent(self, agent: Agent) -> None:
        self._agents = [a for a in self._agents if a.identity != agent.identity]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity != agent.identity
        ]

    def _dismiss_planned_agent(self, agent: Agent, _cleanup_plan: object) -> None:
        self._dismiss_done_agent(agent)

    def _plan_focused_agent_cleanup(self, agent: Agent) -> object:
        from sase.core.agent_cleanup_wire import (
            AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            AgentCleanupDismissItemWire,
            AgentCleanupIdentityWire,
            AgentCleanupKillItemWire,
            AgentCleanupPlanWire,
        )

        identity = AgentCleanupIdentityWire(
            agent_type=agent.agent_type.value,
            cl_name=agent.cl_name,
            raw_suffix=agent.raw_suffix,
        )
        if agent.pid is None:
            return AgentCleanupPlanWire(
                schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
                dismiss_items=(AgentCleanupDismissItemWire(identity),),
            )
        return AgentCleanupPlanWire(
            schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            kill_items=(
                AgentCleanupKillItemWire(
                    identity=identity,
                    kind="running",
                    pid=agent.pid,
                ),
            ),
        )

    def _get_selected_agent(self) -> Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def _agents_in_focused_panel(self) -> list[Agent]:
        panel_group = getattr(self, "_panel_group", None)
        if panel_group is None:
            return list(self._agents)

        from sase.ace.tui.actions.agents._navigation_order import (
            rendered_panel_slice,
        )

        _global_indices, agents = rendered_panel_slice(self, panel_group.focused_key)
        return list(agents)


def test_action_kill_routes_to_group_when_banner_focused() -> None:
    """With no marks but a banner focused, x bulk-kills every agent in the group."""
    a1 = _make_agent(
        cl_name="release-fix",
        project_file="/tmp/projects/proj_a/proj_a.sase",
        raw_suffix="20240101120000",
    )
    a2 = _make_agent(
        cl_name="release-fix",
        project_file="/tmp/projects/proj_a/proj_a.sase",
        raw_suffix="20240101130000",
    )
    a3 = _make_agent(
        cl_name="other-cl",
        project_file="/tmp/projects/proj_a/proj_a.sase",
        raw_suffix="20240101140000",
    )
    app = _FakeGroupKillApp([a1, a2, a3])
    app._current_group_key = ("proj_a", "release-fix")

    with patch.object(app, "_do_bulk_kill_agents") as mock_bulk:
        app.action_kill_agent()
        assert app.pushed_callbacks, "Modal callback not registered"
        # User confirms
        app.pushed_callbacks[0](True)

    # Both project+cl agents go into killable; the other-cl agent is in a
    # separate banner.
    args, _ = mock_bulk.call_args
    killable = args[0]
    dismissable = args[1] if len(args) > 1 else []
    killed_ids = {a.identity for a in killable}
    dismissed_ids = {a.identity for a in dismissable}
    assert killed_ids == {a1.identity, a2.identity}
    assert dismissed_ids == set()
    assert a3.identity not in killed_ids


def test_action_kill_on_clan_container_cascades_to_real_members() -> None:
    running = _make_agent(
        cl_name="research.one",
        raw_suffix="20260717100001",
        agent_clan="research",
        agent_clan_generation="generation",
        pid=111,
    )
    done = _make_agent(
        cl_name="research.two",
        raw_suffix="20260717100002",
        agent_clan="research",
        agent_clan_generation="generation",
        status="DONE",
        pid=None,
    )
    projected = project_clan_tree([running, done])
    container = projected[0]
    app = _FakeGroupKillApp(projected)

    with patch.object(app, "_do_bulk_kill_agents") as mock_bulk:
        app.action_kill_agent()
        app.pushed_callbacks[0](True)

    mock_bulk.assert_called_once_with([running], [done])
    assert container not in mock_bulk.call_args.args[0]
    description = app.pushed_modals[0].agent_description
    assert "Clan: research" in description
    assert "Kill: 1 sase agent" in description
    assert "Dismiss: 1 sase agent" in description


def test_group_kill_modal_header_includes_label_and_section_count() -> None:
    """The scope stays label-only while the section carries its sase-agent count."""
    a1 = _make_agent(
        cl_name="release-fix",
        project_file="/tmp/projects/proj_a/proj_a.sase",
        raw_suffix="20240101120000",
    )
    a2 = _make_agent(
        cl_name="release-fix",
        project_file="/tmp/projects/proj_a/proj_a.sase",
        raw_suffix="20240101130000",
    )
    app = _FakeGroupKillApp([a1, a2])
    app._current_group_key = ("proj_a", "release-fix")

    app.action_kill_agent()

    assert app.pushed_modals, "Expected a confirmation modal"
    description = app.pushed_modals[0].agent_description
    assert "Group: release-fix" in description
    assert "Group: release-fix (" not in description
    assert "Kill: 2 sase agents" in description


def test_group_kill_partitions_killable_and_dismissable() -> None:
    """A group containing both running and done agents partitions correctly."""
    running = _make_agent(
        cl_name="release-fix",
        project_file="/tmp/projects/proj_a/proj_a.sase",
        raw_suffix="20240101120000",
        status="RUNNING",
        pid=111,
    )
    done = _make_agent(
        cl_name="release-fix",
        project_file="/tmp/projects/proj_a/proj_a.sase",
        raw_suffix="20240101130000",
        status="DONE",
        pid=None,
    )
    app = _FakeGroupKillApp([running, done])
    app._current_group_key = ("proj_a", "release-fix")

    with patch.object(app, "_do_bulk_kill_agents") as mock_bulk:
        app.action_kill_agent()
        app.pushed_callbacks[0](True)

    mock_bulk.assert_called_once_with([running], [done])


def test_group_kill_cancel_leaves_agents_untouched() -> None:
    """Cancelling the modal does not invoke _do_bulk_kill_agents."""
    a1 = _make_agent(raw_suffix="20240101120000")
    a2 = _make_agent(raw_suffix="20240101130000")
    app = _FakeGroupKillApp([a1, a2])
    app._current_group_key = ("proj_a", "fix-bug")

    with patch.object(app, "_do_bulk_kill_agents") as mock_bulk:
        app.action_kill_agent()
        app.pushed_callbacks[0](False)

    mock_bulk.assert_not_called()


def test_marks_take_priority_over_focused_group() -> None:
    """When marks exist, x ignores the focused group and bulk-kills marks."""
    marked = _make_agent(
        cl_name="fix-bug",
        project_file="/tmp/projects/proj_a/proj_a.sase",
        raw_suffix="20240101110000",
    )
    in_group = _make_agent(
        cl_name="fix-bug",
        project_file="/tmp/projects/proj_a/proj_a.sase",
        raw_suffix="20240101120000",
    )
    app = _FakeGroupKillApp([marked, in_group])
    app._marked_agents = {marked.identity}
    app._current_group_key = ("proj_a", "fix-bug")

    with patch.object(app, "_do_bulk_kill_agents") as mock_bulk:
        app.action_kill_agent()
        app.pushed_callbacks[0](True)

    args, _ = mock_bulk.call_args
    killable_ids = {a.identity for a in args[0]}
    # Only the marked agent is in the kill set, not the whole group.
    assert killable_ids == {marked.identity}


def test_group_kill_skips_workflow_children() -> None:
    """Workflow children are excluded; killing the parent cascades elsewhere."""
    parent = _make_agent(
        cl_name="parent",
        project_file="/tmp/projects/proj_a/proj_a.sase",
        raw_suffix="20240101120000",
        agent_type=AgentType.WORKFLOW,
    )
    child = _make_agent(
        cl_name="parent",
        project_file="/tmp/projects/proj_a/proj_a.sase",
        raw_suffix="20240101120100",
        parent_timestamp="20240101120000",
    )
    app = _FakeGroupKillApp([parent, child])
    app._current_group_key = ("proj_a", "parent")

    with patch.object(app, "_do_bulk_kill_agents") as mock_bulk:
        app.action_kill_agent()
        app.pushed_callbacks[0](True)

    args, _ = mock_bulk.call_args
    killable_ids = {a.identity for a in args[0]}
    assert parent.identity in killable_ids
    # Child is not directly listed — kill cascades via _collect_immediate_kill_identities.
    assert child.identity not in killable_ids


def test_group_kill_no_op_when_group_key_does_not_match() -> None:
    """A stale group_key (group no longer visible) falls through to single-agent path."""
    a1 = _make_agent(
        cl_name="alone",
        raw_suffix="20240101120000",
        status="DONE",
        pid=None,
    )
    app = _FakeGroupKillApp([a1])
    app._current_group_key = ("nonexistent",)

    # Falls through to single-agent path (DONE -> dismiss without modal).
    # We just verify no group modal was pushed.
    with patch.object(app, "_dismiss_planned_agent") as mock_dismiss:
        app.action_kill_agent()

    mock_dismiss.assert_called_once()
    assert mock_dismiss.call_args.args[0] == a1
    assert app.pushed_modals == []


def test_group_kill_by_date_is_scoped_to_focused_panel() -> None:
    """Same-hour agents in another tribe panel are not killed."""
    now = datetime(2026, 7, 13, 12, 0, 0)
    epic_a = _make_agent(
        cl_name="epic-a",
        raw_suffix="20260713100500",
        start_time=datetime(2026, 7, 13, 10, 5, 0),
        tribe="epic",
    )
    no_tribe_a = _make_agent(
        cl_name="no_tribe-a",
        raw_suffix="20260713101000",
        start_time=datetime(2026, 7, 13, 10, 10, 0),
    )
    epic_b = _make_agent(
        cl_name="epic-b",
        raw_suffix="20260713102000",
        start_time=datetime(2026, 7, 13, 10, 20, 0),
        tribe="epic",
    )
    no_tribe_b = _make_agent(
        cl_name="no_tribe-b",
        raw_suffix="20260713103000",
        start_time=datetime(2026, 7, 13, 10, 30, 0),
    )
    app = _FakeGroupKillApp([epic_a, no_tribe_a, epic_b, no_tribe_b])
    app._panel_group = AgentPanelGroup.from_agents(app._agents, focused_key=None)
    app._grouping_mode = GroupingMode.BY_DATE
    app._current_group_key = ("Today", "10:00")

    with patch("sase.ace.tui.models.agent_groups._tree.local_now", return_value=now):
        app.action_kill_agent()

    assert app.pushed_callbacks, "Modal callback not registered"
    app.pushed_callbacks[0](True)

    assert {agent.identity for agent in app._agents} == {
        epic_a.identity,
        epic_b.identity,
    }


def test_group_kill_standard_mode_is_scoped_to_focused_panel() -> None:
    """A project banner targets only its focused tribe panel."""
    epic = _make_agent(
        cl_name="epic-change",
        raw_suffix="20260713100500",
        tribe="epic",
    )
    no_tribe = _make_agent(
        cl_name="no_tribe-change",
        raw_suffix="20260713101000",
    )
    app = _FakeGroupKillApp([epic, no_tribe])
    app._panel_group = AgentPanelGroup.from_agents(app._agents, focused_key=None)
    app._grouping_mode = GroupingMode.STANDARD
    app._current_group_key = ("proj_a",)

    app.action_kill_agent()
    assert app.pushed_callbacks, "Modal callback not registered"
    app.pushed_callbacks[0](True)

    assert [agent.identity for agent in app._agents] == [epic.identity]


def test_focused_running_kill_subject_uses_sase_agent() -> None:
    agent = _make_agent(
        cl_name="focused-change",
        raw_suffix="20260713100500",
        agent_name="focused-lane",
        workspace_num=17,
        pid=7123,
    )
    app = _FakeGroupKillApp([agent])

    app.action_kill_agent()

    assert app.pushed_modals[0].agent_description == (
        "Sase agent:\n  focused-lane\nType: run\nWorkspace: #17\nPID: 7123"
    )


def test_cleanup_group_count_is_scoped_to_focused_panel() -> None:
    """Cleanup-panel group stats exclude same-key groups in other panels."""
    epic_a = _make_agent(
        cl_name="epic-a",
        raw_suffix="20260713100500",
        tribe="epic",
    )
    no_tribe_a = _make_agent(
        cl_name="no_tribe-a",
        raw_suffix="20260713101000",
    )
    epic_b = _make_agent(
        cl_name="epic-b",
        raw_suffix="20260713102000",
        tribe="epic",
    )
    no_tribe_b = _make_agent(
        cl_name="no_tribe-b",
        raw_suffix="20260713103000",
    )
    app = _FakeGroupKillApp([epic_a, no_tribe_a, epic_b, no_tribe_b])
    app._panel_group = AgentPanelGroup.from_agents(app._agents, focused_key=None)
    app._grouping_mode = GroupingMode.STANDARD
    app._current_group_key = ("proj_a",)

    state = app._build_agent_cleanup_panel_state()

    assert state.group_count == 2
