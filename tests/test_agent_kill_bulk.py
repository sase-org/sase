"""Tests for `_do_bulk_kill_agents` (multi-agent kill flow)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from sase.ace.tui.actions.agents._kill_persistence import BulkKillItem
from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.notification_store_wire import NotificationUpdateOutcomeWire

from tests._agent_cleanup_proc_helpers import (
    TrackedProcRecorderMixin,
    run_tracked_proc,
)


def _user_kill_result(
    *, success: bool = True, status: str = "killed", error: str | None = None
) -> SimpleNamespace:
    return SimpleNamespace(success=success, status=status, error=error)


def test_do_bulk_kill_agents_refreshes_and_schedules_once() -> None:
    """Bulk kill should remove all rows immediately with one refresh/task."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(TrackedProcRecorderMixin, AgentsMixin):
        def __init__(self) -> None:
            self._init_tracked_task_recorder()
            self._notifications: list[tuple[str, str]] = []
            self.current_tab = "agents"
            self.current_idx = 0
            self._kill_persistence_inflight = set()
            self._agent_status_overrides = {}
            self._agent_pre_question_status = {}
            self._dismissed_agents = set()
            self._dismissed_agent_objects = []
            self._marked_agents = set()
            self._agents_with_children = []
            self._agents = []
            self._scheduled: list[tuple[object, tuple[object, ...]]] = []
            self.refresh_calls: list[tuple[bool, bool]] = []
            self.notification_refreshes = 0

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _refresh_notification_count(self) -> None:
            self.notification_refreshes += 1

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
    a1 = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature_one",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        pid=111,
        raw_suffix="fix_hook-111-251230_151429",
    )
    a2 = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature_two",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="mentor",
        pid=222,
        raw_suffix="mentor_complete-222-251230_151429",
    )
    app._agents = [a1, a2]
    app._agents_with_children = [a1, a2]
    app._marked_agents = {a1.identity, a2.identity}

    with patch(
        "sase.ace.tui.actions.agents._killing.request_user_kill",
        return_value=_user_kill_result(),
    ) as mock_request_user_kill:
        app._do_bulk_kill_agents([a1, a2])

    assert [call.args[0] for call in mock_request_user_kill.call_args_list] == [
        111,
        222,
    ]
    assert [
        (
            call.kwargs["source"],
            call.kwargs["wait"],
            call.kwargs["background"],
            call.kwargs["reason"],
        )
        for call in mock_request_user_kill.call_args_list
    ] == [
        ("ace_tui", False, True, a1.display_name),
        ("ace_tui", False, True, a2.display_name),
    ]
    assert app._agents == []
    assert app._agents_with_children == []
    assert app._marked_agents == set()
    assert a1.identity in app._dismissed_agents
    assert a2.identity in app._dismissed_agents
    assert app.refresh_calls == [(True, True)]
    # Phase 1: notification count refresh is now done in the async worker,
    # not synchronously in _do_bulk_kill_agents.
    assert app.notification_refreshes == 0
    # Persistence is submitted as one tracked background task; no ad hoc
    # call_later coroutine remains.
    assert app._scheduled == []
    assert len(app.tracked_procs) == 1
    task = app.tracked_procs[0]
    assert task["proc_type"] == "kill"
    assert task["display_name"] == "kill 2 agents"
    assert app._kill_persistence_inflight == {a1.identity, a2.identity}


def test_do_bulk_kill_agents_removes_workflow_children_immediately() -> None:
    """Killing a workflow parent should hide its step rows in the same refresh."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(TrackedProcRecorderMixin, AgentsMixin):
        def __init__(self) -> None:
            self._init_tracked_task_recorder()
            self._notifications: list[tuple[str, str]] = []
            self.current_tab = "agents"
            self.current_idx = 0
            self._kill_persistence_inflight = set()
            self._agent_status_overrides = {}
            self._agent_pre_question_status = {}
            self._dismissed_agents = set()
            self._dismissed_agent_objects = []
            self._marked_agents = set()
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
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="wf",
        pid=333,
        raw_suffix="20240101120000",
    )
    child = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="step",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="step",
        pid=None,
        raw_suffix="step-1",
        parent_workflow="wf",
        parent_timestamp="20240101120000",
    )
    app._agents = [parent, child]
    app._agents_with_children = [parent, child]

    with patch(
        "sase.ace.tui.actions.agents._killing.request_user_kill",
        return_value=_user_kill_result(),
    ):
        app._do_bulk_kill_agents([parent])

    assert app._agents == []
    assert app._agents_with_children == []
    assert parent.identity in app._dismissed_agents
    assert child.identity in app._dismissed_agents
    assert app.refresh_calls == [(True, True)]


def test_do_bulk_kill_agents_failed_pid_stays_visible() -> None:
    """A failed process-group kill should not remove that agent."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(TrackedProcRecorderMixin, AgentsMixin):
        def __init__(self) -> None:
            self._init_tracked_task_recorder()
            self._notifications: list[tuple[str, str]] = []
            self.current_tab = "agents"
            self.current_idx = 0
            self._kill_persistence_inflight = set()
            self._agent_status_overrides = {}
            self._agent_pre_question_status = {}
            self._dismissed_agents = set()
            self._dismissed_agent_objects = []
            self._marked_agents = set()
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
    failed = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="failed",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        pid=111,
        raw_suffix="fix_hook-111-251230_151429",
    )
    killed = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="killed",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="mentor",
        pid=222,
        raw_suffix="mentor_complete-222-251230_151429",
    )
    app._agents = [failed, killed]
    app._agents_with_children = [failed, killed]

    def fake_request_user_kill(pid: int, **_kwargs: object) -> SimpleNamespace:
        if pid == 111:
            return _user_kill_result(
                success=False,
                status="permission_denied",
                error="permission denied",
            )
        return _user_kill_result()

    with patch(
        "sase.ace.tui.actions.agents._killing.request_user_kill",
        side_effect=fake_request_user_kill,
    ):
        app._do_bulk_kill_agents([failed, killed])

    assert app._agents == [failed]
    assert app._agents_with_children == [failed]
    assert failed.identity not in app._dismissed_agents
    assert killed.identity in app._dismissed_agents
    assert app.refresh_calls == [(True, True)]


def test_run_bulk_kill_persistence_does_not_refresh_on_success() -> None:
    """Successful bulk cleanup should not schedule a redundant full reload."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(TrackedProcRecorderMixin, AgentsMixin):
        def __init__(self) -> None:
            self._init_tracked_task_recorder()
            self._notifications: list[tuple[str, str]] = []
            self._kill_persistence_inflight = set()
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
        cl_name="feature_one",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        pid=111,
        raw_suffix="fix_hook-111-251230_151429",
    )
    item = BulkKillItem(agent=agent, kind="hook", identities={agent.identity})
    dismissed_snapshot = {agent.identity}

    with patch(
        "sase.ace.tui.actions.agents._killing.persist_bulk_kill_side_effects"
    ) as mock_persist:
        app._submit_bulk_kill_persistence_proc([item], [], dismissed_snapshot, [agent])
        run_tracked_proc(app, app.tracked_procs[0])

    mock_persist.assert_called_once_with([item], [], dismissed_snapshot, [agent])
    assert app.refresh_schedules == 0
    assert app.async_count_refreshes == 1
    assert app._notifications == []
    assert app._kill_persistence_inflight == set()


def test_run_bulk_kill_persistence_refreshes_on_failure() -> None:
    """Failed bulk cleanup still schedules a reload to reconcile with disk."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(TrackedProcRecorderMixin, AgentsMixin):
        def __init__(self) -> None:
            self._init_tracked_task_recorder()
            self._notifications: list[tuple[str, str]] = []
            self._kill_persistence_inflight = set()
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
        cl_name="feature_one",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        pid=111,
        raw_suffix="fix_hook-111-251230_151429",
    )
    item = BulkKillItem(agent=agent, kind="hook", identities={agent.identity})
    dismissed_snapshot = {agent.identity}

    with patch(
        "sase.ace.tui.actions.agents._killing.persist_bulk_kill_side_effects",
        side_effect=RuntimeError("boom"),
    ) as mock_persist:
        app._submit_bulk_kill_persistence_proc([item], [], dismissed_snapshot, [agent])
        run_tracked_proc(app, app.tracked_procs[0])

    mock_persist.assert_called_once_with([item], [], dismissed_snapshot, [agent])
    assert app.refresh_schedules == 1
    assert app._notifications == [("Bulk kill cleanup failed: boom", "error")]
    assert app._kill_persistence_inflight == set()


def test_persist_bulk_kill_side_effects_uses_one_notification_update() -> None:
    """Bulk kill/dismiss cleanup batches notification dismissal into one Rust update."""
    from sase.ace.tui.actions.agents._kill_persistence import (
        persist_bulk_kill_side_effects,
    )

    running = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature_one",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        pid=111,
        raw_suffix="20260501010101",
    )
    done = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature_two",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=None,
        workflow="mentor",
        pid=None,
        raw_suffix="20260501020202",
    )
    item = BulkKillItem(agent=running, kind="hook", identities={running.identity})
    outcome = NotificationUpdateOutcomeWire(
        schema_version=1,
        matched_count=2,
        changed_count=2,
        rewritten=True,
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._kill_persistence.persist_kill_side_effects"
        ),
        patch(
            "sase.ace.tui.actions.agents._kill_persistence.persist_dismiss_side_effects"
        ),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch(
            "sase.ace.tui.actions.agents._kill_persistence."
            "sync_dismissed_agent_artifact_index"
        ) as mock_sync_index,
        patch(
            "sase.notifications.store._rust_apply_notification_state_update",
            return_value=outcome,
        ) as mock_update,
    ):
        persist_bulk_kill_side_effects(
            [item],
            [done],
            {running.identity, done.identity},
            [running, done],
        )

    mock_update.assert_called_once()
    mock_sync_index.assert_called_once_with({running.identity, done.identity})
    update = mock_update.call_args.args[1]
    assert update.kind == "dismiss_matching_agents"
    assert [(agent.cl_name, agent.raw_suffix) for agent in update.agents] == [
        ("feature_one", "20260501010101"),
        ("feature_two", "20260501020202"),
    ]


def test_single_kill_transaction_skips_artifact_index_when_save_skipped() -> None:
    """A stale or failed dismissed-set save must not sync stale index state."""
    from sase.ace.tui.actions.agents._kill_transactions import (
        persist_single_kill_transaction,
    )

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature_one",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        pid=111,
        raw_suffix="20260501010101",
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._killing.persist_kill_side_effects",
            return_value=True,
        ),
        patch(
            "sase.ace.dismissed_agents.save_dismissed_agents",
            return_value=False,
        ) as mock_save,
        patch(
            "sase.ace.tui.actions.agents._killing.sync_dismissed_agent_artifact_index"
        ) as mock_sync_index,
        patch(
            "sase.ace.tui.actions.agents._killing.dismiss_notifications_for_agents"
        ) as mock_dismiss_notifications,
    ):
        persist_single_kill_transaction(
            agent,
            "running",
            [agent],
            {agent.identity},
            None,
            [agent],
        )

    mock_save.assert_called_once_with({agent.identity})
    mock_sync_index.assert_not_called()
    mock_dismiss_notifications.assert_not_called()
