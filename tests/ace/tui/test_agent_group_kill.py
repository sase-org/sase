"""Phase-5 tests for bulk kill/dismiss on collapsed group rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._kill_action import AgentKillMixin
from sase.ace.tui.actions.agents._marking import AgentMarkingMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry


def _make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for group-kill tests."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "fix-bug",
        "project_file": "/tmp/projects/proj_a/proj_a.gp",
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

    def _get_selected_agent(self) -> Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None


def test_action_kill_routes_to_group_when_banner_focused() -> None:
    """With no marks but a banner focused, x bulk-kills every agent in the group."""
    a1 = _make_agent(
        cl_name="release-fix",
        project_file="/tmp/projects/proj_a/proj_a.gp",
        raw_suffix="20240101120000",
    )
    a2 = _make_agent(
        cl_name="release-fix",
        project_file="/tmp/projects/proj_a/proj_a.gp",
        raw_suffix="20240101130000",
    )
    a3 = _make_agent(
        cl_name="other-cl",
        project_file="/tmp/projects/proj_a/proj_a.gp",
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


def test_group_kill_modal_header_includes_group_label_and_count() -> None:
    """The pushed modal description includes the group banner label."""
    a1 = _make_agent(
        cl_name="release-fix",
        project_file="/tmp/projects/proj_a/proj_a.gp",
        raw_suffix="20240101120000",
    )
    a2 = _make_agent(
        cl_name="release-fix",
        project_file="/tmp/projects/proj_a/proj_a.gp",
        raw_suffix="20240101130000",
    )
    app = _FakeGroupKillApp([a1, a2])
    app._current_group_key = ("proj_a", "release-fix")

    app.action_kill_agent()

    assert app.pushed_modals, "Expected a confirmation modal"
    description = app.pushed_modals[0].agent_description
    assert "release-fix" in description
    assert "2 agent" in description


def test_group_kill_partitions_killable_and_dismissable() -> None:
    """A group containing both running and done agents partitions correctly."""
    running = _make_agent(
        cl_name="release-fix",
        project_file="/tmp/projects/proj_a/proj_a.gp",
        raw_suffix="20240101120000",
        status="RUNNING",
        pid=111,
    )
    done = _make_agent(
        cl_name="release-fix",
        project_file="/tmp/projects/proj_a/proj_a.gp",
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
        project_file="/tmp/projects/proj_a/proj_a.gp",
        raw_suffix="20240101110000",
    )
    in_group = _make_agent(
        cl_name="fix-bug",
        project_file="/tmp/projects/proj_a/proj_a.gp",
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
        project_file="/tmp/projects/proj_a/proj_a.gp",
        raw_suffix="20240101120000",
        agent_type=AgentType.WORKFLOW,
    )
    child = _make_agent(
        cl_name="parent",
        project_file="/tmp/projects/proj_a/proj_a.gp",
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

    # Falls through to single-agent path (DONE → dismiss without modal).
    # We just verify no group modal was pushed.
    with patch.object(app, "_dismiss_done_agent") as mock_dismiss:
        app.action_kill_agent()

    mock_dismiss.assert_called_once_with(a1)
    assert app.pushed_modals == []
