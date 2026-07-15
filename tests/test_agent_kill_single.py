"""Tests for `_do_kill_agent` (single-agent kill flow)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.ace.tui.actions.agents import AgentsMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.notifications import Notification, append_notification, load_notifications

from tests._agent_cleanup_task_helpers import (
    TrackedTaskRecorderMixin,
    run_tracked_task,
)


def _cleanup_plan(agent: Agent, *, action: str, kind: str = "running") -> object:
    from sase.core.agent_cleanup_wire import (
        AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        AgentCleanupDismissItemWire,
        AgentCleanupIdentityWire,
        AgentCleanupKillItemWire,
        AgentCleanupPlanWire,
        AgentCleanupSideEffectsWire,
    )

    identity = AgentCleanupIdentityWire(
        agent_type=agent.agent_type.value,
        cl_name=agent.cl_name,
        raw_suffix=agent.raw_suffix,
    )
    kill_items = ()
    dismiss_items = ()
    if action == "kill":
        kill_items = (
            AgentCleanupKillItemWire(
                identity=identity,
                kind=kind,
                pid=agent.pid,
                display_name=agent.display_name,
            ),
        )
    elif action == "dismiss":
        dismiss_items = (
            AgentCleanupDismissItemWire(
                identity=identity,
                display_name=agent.display_name,
            ),
        )
    return AgentCleanupPlanWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        selected_identities=(identity,),
        kill_items=kill_items,
        dismiss_items=dismiss_items,
        side_effects=AgentCleanupSideEffectsWire(
            dismissed_index_additions=(identity,),
        ),
    )


class _ActionApp(AgentsMixin):
    def __init__(self, agent: Agent | list[Agent], *, current_idx: int = 0) -> None:
        agents = list(agent) if isinstance(agent, list) else [agent]
        self.current_tab = "agents"
        self.current_idx = current_idx
        self._agents = agents
        self._agents_with_children = list(agents)
        self._marked_agents = set()
        self._current_group_key = None
        self._notifications: list[tuple[str, str]] = []
        self.pushed: list[tuple[object, object]] = []

    def notify(self, msg: str, severity: str = "information") -> None:
        self._notifications.append((msg, severity))

    def push_screen(self, modal: object, callback: object = None) -> None:
        self.pushed.append((modal, callback))

    def _get_selected_agent(self) -> Agent | None:
        return self._agents[self.current_idx] if self._agents else None


def test_action_kill_single_running_uses_cleanup_planner_before_confirm() -> None:
    from sase.core.agent_cleanup_wire import (
        CLEANUP_MODE_KILL_AND_DISMISS,
        CLEANUP_SCOPE_EXPLICIT_IDENTITIES,
    )

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=12345,
        raw_suffix="run-12345",
    )
    app = _ActionApp(agent)
    plan = _cleanup_plan(agent, action="kill")

    with (
        patch(
            "sase.core.agent_cleanup_facade.plan_agent_cleanup", return_value=plan
        ) as mock_plan,
        patch.object(app, "_do_kill_agent") as mock_do_kill,
    ):
        app.action_kill_agent()
        assert app.pushed
        app.pushed[0][1](True)  # type: ignore[index,operator]

    _, request = mock_plan.call_args.args
    assert request.scope == CLEANUP_SCOPE_EXPLICIT_IDENTITIES
    assert request.mode == CLEANUP_MODE_KILL_AND_DISMISS
    assert request.identities[0].raw_suffix == agent.raw_suffix
    assert request.include_pidless_as_dismissable is True
    mock_do_kill.assert_called_once_with(agent, plan)


def test_action_kill_single_done_uses_planner_backed_dismiss() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="done_feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=None,
        workflow=None,
        pid=None,
        raw_suffix="done-12345",
    )
    app = _ActionApp(agent)
    plan = _cleanup_plan(agent, action="dismiss")

    with (
        patch("sase.core.agent_cleanup_facade.plan_agent_cleanup", return_value=plan),
        patch.object(app, "_dismiss_planned_agent") as mock_dismiss,
    ):
        app.action_kill_agent()

    mock_dismiss.assert_called_once_with(agent, plan)
    assert app.pushed == []


def test_action_kill_single_pidless_running_is_planned_as_dismissable() -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="pidless_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=None,
        raw_suffix="pidless-12345",
    )
    app = _ActionApp(agent)
    plan = _cleanup_plan(agent, action="dismiss")

    with (
        patch(
            "sase.core.agent_cleanup_facade.plan_agent_cleanup", return_value=plan
        ) as mock_plan,
        patch.object(app, "_dismiss_planned_agent") as mock_dismiss,
    ):
        app.action_kill_agent()

    _, request = mock_plan.call_args.args
    assert request.include_pidless_as_dismissable is True
    mock_dismiss.assert_called_once_with(agent, plan)


def test_action_kill_running_child_opens_confirmation_for_child() -> None:
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="parent_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=111,
        raw_suffix="parent-12345",
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
    )
    app = _ActionApp([parent, child], current_idx=1)
    plan = _cleanup_plan(child, action="kill")

    with (
        patch("sase.core.agent_cleanup_facade.plan_agent_cleanup", return_value=plan),
        patch.object(app, "_do_kill_agent") as mock_do_kill,
    ):
        app.action_kill_agent()
        assert app.pushed
        app.pushed[0][1](True)  # type: ignore[index,operator]

    mock_do_kill.assert_called_once_with(child, plan)


def test_action_kill_completed_child_dismisses_child() -> None:
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="parent_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=111,
        raw_suffix="parent-12345",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="child_feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=None,
        workflow=None,
        pid=None,
        raw_suffix="child-12345",
        parent_timestamp="parent-12345",
    )
    app = _ActionApp([parent, child], current_idx=1)
    plan = _cleanup_plan(child, action="dismiss")

    with (
        patch("sase.core.agent_cleanup_facade.plan_agent_cleanup", return_value=plan),
        patch.object(app, "_dismiss_planned_agent") as mock_dismiss,
    ):
        app.action_kill_agent()

    mock_dismiss.assert_called_once_with(child, plan)
    assert app.pushed == []


def test_no_focused_cleanup_action_prefers_focused_skip_reason() -> None:
    from sase.core.agent_cleanup_wire import (
        AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        SKIPPED_NOT_IN_SCOPE,
        SKIPPED_NOT_KILLABLE,
        AgentCleanupIdentityWire,
        AgentCleanupPlanWire,
        AgentCleanupSkippedItemWire,
    )

    other = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="other_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=None,
        raw_suffix="other-12345",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="child_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow=None,
        pid=None,
        raw_suffix="child-12345",
        parent_timestamp="parent-12345",
    )
    app = _ActionApp([other, child], current_idx=1)
    plan = AgentCleanupPlanWire(
        schema_version=AGENT_CLEANUP_WIRE_SCHEMA_VERSION,
        skipped_items=(
            AgentCleanupSkippedItemWire(
                identity=AgentCleanupIdentityWire(
                    agent_type=other.agent_type.value,
                    cl_name=other.cl_name,
                    raw_suffix=other.raw_suffix,
                ),
                reason=SKIPPED_NOT_IN_SCOPE,
            ),
            AgentCleanupSkippedItemWire(
                identity=AgentCleanupIdentityWire(
                    agent_type=child.agent_type.value,
                    cl_name=child.cl_name,
                    raw_suffix=child.raw_suffix,
                ),
                reason=SKIPPED_NOT_KILLABLE,
                detail="RUNNING",
            ),
        ),
    )

    app._notify_no_focused_cleanup_action(plan, child)

    assert app._notifications == [
        ("Agent cannot be cleaned up (not_killable: RUNNING)", "warning")
    ]


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
    )
    app = MockApp()
    app._agents = [parent, child, sibling]
    app._agents_with_children = [parent, child, sibling]

    with patch(
        "sase.ace.tui.actions.agents._killing.request_user_kill",
        return_value=SimpleNamespace(success=True, status="killed", error=None),
    ):
        app._do_kill_agent(child, _cleanup_plan(child, action="kill"))

    assert app._agents == [parent, sibling]
    assert app._agents_with_children == [parent, sibling]
    assert child.identity in app._dismissed_agents
    assert parent.identity not in app._dismissed_agents
    assert sibling.identity not in app._dismissed_agents
    assert app.refresh_calls == [(True, True)]


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


def test_ace_root_only_kill_cleanup_dismisses_child_question(
    tmp_path: Path,
) -> None:
    """A focused root cleanup reaches a child-routed question via the backend."""
    from sase.ace.tui.actions.agents._kill_transactions import (
        persist_single_kill_transaction,
    )
    from sase.core.agent_cleanup_wire import (
        AgentCleanupNotificationDismissIntentWire,
        AgentCleanupSideEffectsWire,
    )

    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        pid=12345,
        raw_suffix="20260715100000",
    )
    plan = _cleanup_plan(root, action="kill")
    identity = plan.selected_identities[0]
    plan = replace(
        plan,
        side_effects=AgentCleanupSideEffectsWire(
            dismissed_index_additions=(identity,),
            notification_dismiss_candidates=(
                AgentCleanupNotificationDismissIntentWire(
                    identity=identity,
                    cl_name=root.cl_name,
                    raw_suffix=root.raw_suffix,
                ),
            ),
        ),
    )
    response_dir = tmp_path / "response"
    response_dir.mkdir()
    notifications_dir = tmp_path / "notifications"

    with (
        patch(
            "sase.notifications.store.NOTIFICATIONS_DIR",
            str(notifications_dir),
        ),
        patch(
            "sase.notifications.store.NOTIFICATIONS_FILE",
            str(notifications_dir / "notifications.jsonl"),
        ),
        patch("sase.ace.dismissed_agents.save_dismissed_agents", return_value=False),
    ):
        append_notification(
            Notification(
                id="question",
                timestamp="2026-07-15T10:00:00-04:00",
                sender="question",
                action="UserQuestion",
                action_data={
                    "agent_cl_name": root.cl_name,
                    "agent_timestamp": "20260715100001",
                    "agent_root_timestamp": root.raw_suffix or "",
                    "response_dir": str(response_dir),
                },
            )
        )
        append_notification(
            Notification(
                id="unrelated",
                timestamp="2026-07-15T10:00:01-04:00",
                sender="question",
                action="UserQuestion",
                action_data={
                    "agent_cl_name": root.cl_name,
                    "agent_timestamp": "20260715100002",
                    "agent_root_timestamp": "20260715999999",
                },
            )
        )

        persist_single_kill_transaction(
            root,
            "running",
            [root],
            {root.identity},
            plan,
            [root],
        )

        by_id = {n.id: n for n in load_notifications(include_dismissed=True)}

    assert by_id["question"].dismissed is True
    assert by_id["unrelated"].dismissed is False
    assert not (response_dir / "question_response.json").exists()


def test_run_kill_persistence_does_not_refresh_on_success() -> None:
    """Successful cleanup should not schedule a redundant full agent reload."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(TrackedTaskRecorderMixin, AgentsMixin):
        def __init__(self) -> None:
            self._init_tracked_task_recorder()
            self._notifications: list[tuple[str, str]] = []
            self._kill_persistence_inflight = set()
            self._dismissed_agents = set()
            self._agents_with_children = []
            self._scheduled: list[tuple[object, tuple[object, ...]]] = []
            self.refresh_schedules = 0
            self.async_count_refreshes = 0

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def call_later(self, callback: object, *args: object) -> None:
            self._scheduled.append((callback, args))

        def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
            del source
            self.refresh_schedules += 1

        async def _refresh_notification_count_async(self) -> None:
            self.async_count_refreshes += 1

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
    app._dismissed_agents = {agent.identity}

    with (
        patch(
            "sase.ace.tui.actions.agents._killing.persist_kill_side_effects"
        ) as mock_persist,
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
        patch(
            "sase.ace.tui.actions.agents._killing.dismiss_notifications_for_agents"
        ) as mock_dismiss_notifs,
    ):
        app._submit_kill_persistence_task(agent, "hook", [agent])
        run_tracked_task(app, app.tracked_tasks[0])

    mock_persist.assert_called_once_with(agent, "hook", [agent])
    mock_save.assert_called_once_with({agent.identity})
    mock_dismiss_notifs.assert_called_once_with([agent])
    assert app.refresh_schedules == 0
    assert app.async_count_refreshes == 1
    assert app._notifications == []
    assert app._kill_persistence_inflight == set()


def test_run_kill_persistence_refreshes_on_failure() -> None:
    """Failed cleanup still schedules a reload to reconcile with disk."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(TrackedTaskRecorderMixin, AgentsMixin):
        def __init__(self) -> None:
            self._init_tracked_task_recorder()
            self._notifications: list[tuple[str, str]] = []
            self._kill_persistence_inflight = set()
            self._dismissed_agents = set()
            self._agents_with_children = []
            self._scheduled: list[tuple[object, tuple[object, ...]]] = []
            self.refresh_schedules = 0
            self.async_count_refreshes = 0

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def call_later(self, callback: object, *args: object) -> None:
            self._scheduled.append((callback, args))

        def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
            del source
            self.refresh_schedules += 1

        async def _refresh_notification_count_async(self) -> None:
            self.async_count_refreshes += 1

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

    with (
        patch(
            "sase.ace.tui.actions.agents._killing.persist_kill_side_effects",
            side_effect=RuntimeError("boom"),
        ) as mock_persist,
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
    ):
        app._submit_kill_persistence_task(agent, "hook", [agent])
        run_tracked_task(app, app.tracked_tasks[0])

    mock_persist.assert_called_once_with(agent, "hook", [agent])
    mock_save.assert_not_called()
    assert app.refresh_schedules == 1
    assert app._notifications == [("Kill cleanup failed for my_feature: boom", "error")]
    assert app._kill_persistence_inflight == set()
