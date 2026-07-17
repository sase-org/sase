"""Tests for executing a single-agent kill in memory."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from sase.ace.tui.models.agent import Agent, AgentType

from tests._agent_cleanup_task_helpers import (
    TrackedTaskRecorderMixin,
    run_tracked_task,
)
from tests._agent_kill_single_helpers import cleanup_plan


def test_do_kill_agent_removes_in_memory_before_background_persistence() -> None:
    """Kill path should update UI state immediately and defer persistence work."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(TrackedTaskRecorderMixin, AgentsMixin):
        def __init__(self) -> None:
            self._init_tracked_task_recorder()
            self._notifications: list[tuple[str, str]] = []
            self.current_tab = "agents"
            self.current_idx = 0
            self._agents_refresh_pending = False
            self._agents_refresh_scheduled = False
            self._agents_loading = False
            self._kill_persistence_inflight = set()
            self._agent_status_overrides = {}
            self._agent_pre_question_status = {}
            self._dismissed_agents = set()
            self._agents_with_children = []
            self._agents = []
            self._scheduled: list[tuple[object, tuple[object, ...]]] = []
            self.refresh_calls: list[tuple[bool, bool]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _refresh_notification_count(self) -> None:
            return

        def _refresh_agents_display(
            self, *, list_changed: bool = False, defer_detail: bool = False
        ) -> None:
            self.refresh_calls.append((list_changed, defer_detail))

        def call_later(self, callback: object, *args: object) -> None:
            self._scheduled.append((callback, args))

        def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
            del source
            return

    app = MockApp()
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        pid=12345,
        raw_suffix="fix_hook-12345-251230_151429",
    )
    app._agents = [agent]
    app._agents_with_children = [agent]

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_kill_agent(agent)

    assert app._agents == []
    assert agent.identity in app._dismissed_agents
    assert app.refresh_calls == [(True, True)]
    # Persistence is submitted as one tracked background task; no ad hoc
    # call_later coroutine remains.
    assert app._scheduled == []
    assert len(app.tracked_tasks) == 1
    task = app.tracked_tasks[0]
    assert task["task_type"] == "kill"
    assert task["display_name"] == f"kill {agent.display_name}"
    assert agent.identity in app._kill_persistence_inflight


def test_do_kill_agent_child_removes_child_only() -> None:
    """Planner-backed child kills should leave the parent and siblings visible."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(TrackedTaskRecorderMixin, AgentsMixin):
        def __init__(self) -> None:
            self._init_tracked_task_recorder()
            self._notifications: list[tuple[str, str]] = []
            self.current_tab = "agents"
            self.current_idx = 1
            self._agents_refresh_pending = False
            self._agents_refresh_scheduled = False
            self._agents_loading = False
            self._kill_persistence_inflight = set()
            self._agent_status_overrides = {}
            self._agent_pre_question_status = {}
            self._dismissed_agents = set()
            self._agents_with_children = []
            self._agents = []
            self.refresh_calls: list[tuple[bool, bool]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _refresh_notification_count(self) -> None:
            return

        def _refresh_agents_display(
            self, *, list_changed: bool = False, defer_detail: bool = False
        ) -> None:
            self.refresh_calls.append((list_changed, defer_detail))

        def call_later(self, callback: object, *args: object) -> None:
            return

        def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
            del source
            return

    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="parent_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=111,
        raw_suffix="parent-12345",
        agent_family_parallel=True,
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="child_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=222,
        raw_suffix="child-12345",
        parent_timestamp="parent-12345",
        agent_family_parallel=True,
    )
    sibling = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sibling_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=333,
        raw_suffix="sibling-12345",
        parent_timestamp="parent-12345",
        agent_family_parallel=True,
    )
    app = MockApp()
    app._agents = [parent, child, sibling]
    app._agents_with_children = [parent, child, sibling]

    with patch(
        "sase.ace.tui.actions.agents._killing.request_user_kill",
        return_value=SimpleNamespace(success=True, status="killed", error=None),
    ):
        app._do_kill_agent(child, cleanup_plan(child, action="kill"))

    assert app._agents == [parent, sibling]
    assert app._agents_with_children == [parent, sibling]
    assert child.identity in app._dismissed_agents
    assert parent.identity not in app._dismissed_agents
    assert sibling.identity not in app._dismissed_agents
    assert app.refresh_calls == [(True, True)]


def test_do_kill_parallel_family_root_signals_and_removes_every_member() -> None:
    """A root kill must signal independent member process groups before cleanup."""
    from sase.ace.tui.actions.agents import AgentsMixin
    from sase.core.agent_cleanup_facade import (
        _plan_agent_cleanup_python,
        agents_to_cleanup_targets,
    )
    from sase.core.agent_cleanup_wire import (
        AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        CLEANUP_MODE_KILL_AND_DISMISS,
        CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
        AgentCleanupIdentityWire,
        AgentCleanupRequestWire,
    )

    class MockApp(TrackedTaskRecorderMixin, AgentsMixin):
        def __init__(self, agents: list[Agent]) -> None:
            self._init_tracked_task_recorder()
            self._notifications: list[tuple[str, str]] = []
            self.current_tab = "agents"
            self.current_idx = 0
            self._kill_persistence_inflight = set()
            self._agent_status_overrides = {}
            self._agent_pre_question_status = {}
            self._dismissed_agents = set()
            self._agents_with_children = list(agents)
            self._agents = list(agents)

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _refresh_notification_count(self) -> None:
            return

        def _refresh_agents_display(
            self, *, list_changed: bool = False, defer_detail: bool = False
        ) -> None:
            return

        def call_later(self, callback: object, *args: object) -> None:
            return

        def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
            del source

    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase-6g",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        pid=111,
        raw_suffix="root-ts",
        agent_family_parallel=True,
    )
    member_one = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase-6g.1",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        pid=222,
        raw_suffix="member-one-ts",
        parent_timestamp="root-ts",
        agent_family_parallel=True,
    )
    member_two = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase-6g.2",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        pid=333,
        raw_suffix="member-two-ts",
        parent_timestamp="root-ts",
        agent_family_parallel=True,
    )
    agents = [root, member_one, member_two]
    plan = _plan_agent_cleanup_python(
        agents_to_cleanup_targets(agents),
        AgentCleanupRequestWire(
            schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
            scope=CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
            mode=CLEANUP_MODE_KILL_AND_DISMISS,
            identities=(
                AgentCleanupIdentityWire(
                    agent_type=root.agent_type.value,
                    cl_name=root.cl_name,
                    raw_suffix=root.raw_suffix,
                ),
            ),
        ),
    )
    app = MockApp(agents)

    with patch.object(app, "_kill_agent_process_group", return_value=True) as kill:
        app._do_kill_agent(root, plan)

    assert [args.args[0] for args in kill.call_args_list] == agents
    assert app._agents == []
    assert app._agents_with_children == []
    assert app._dismissed_agents == {agent.identity for agent in agents}


def test_do_kill_agent_hook_persistence_runs_async() -> None:
    """Hook project-file writes are deferred to the tracked persistence task."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(TrackedTaskRecorderMixin, AgentsMixin):
        def __init__(self) -> None:
            self._init_tracked_task_recorder()
            self._notifications: list[tuple[str, str]] = []
            self.current_tab = "agents"
            self.current_idx = 0
            self._agents_refresh_pending = False
            self._agents_refresh_scheduled = False
            self._agents_loading = False
            self._kill_persistence_inflight = set()
            self._agent_status_overrides = {}
            self._agent_pre_question_status = {}
            self._dismissed_agents = set()
            self._agents_with_children = []
            self._agents = []
            self._scheduled: list[tuple[object, tuple[object, ...]]] = []
            self.async_count_refreshes = 0

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _refresh_notification_count(self) -> None:
            return

        async def _refresh_notification_count_async(self) -> None:
            self.async_count_refreshes += 1

        def _refresh_agents_display(
            self, *, list_changed: bool = False, defer_detail: bool = False
        ) -> None:
            return

        def call_later(self, callback: object, *args: object) -> None:
            self._scheduled.append((callback, args))

        def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
            del source
            return

    app = MockApp()
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        pid=12345,
        raw_suffix="fix_hook-12345-251230_151429",
    )
    app._agents = [agent]
    app._agents_with_children = [agent]

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_kill_agent(agent)

    with (
        patch(
            "sase.ace.tui.actions.agents._kill_persistence._persist_hook_kill"
        ) as mock_persist_hook,
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.tui.actions.agents._killing.dismiss_notifications_for_agents"),
    ):
        run_tracked_task(app, app.tracked_tasks[0])
        mock_persist_hook.assert_called_once_with(agent)
