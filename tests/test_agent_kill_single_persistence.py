"""Tests for persisting single-agent kill side effects."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.models.agent import Agent, AgentType
from sase.notifications import Notification, append_notification, load_notifications

from tests._agent_cleanup_proc_helpers import (
    TrackedProcRecorderMixin,
    run_tracked_proc,
)
from tests._agent_kill_single_helpers import cleanup_plan


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
    plan = cleanup_plan(root, action="kill")
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

    class MockApp(TrackedProcRecorderMixin, AgentsMixin):
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
        app._submit_kill_persistence_proc(agent, "hook", [agent])
        run_tracked_proc(app, app.tracked_procs[0])

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

    class MockApp(TrackedProcRecorderMixin, AgentsMixin):
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
        app._submit_kill_persistence_proc(agent, "hook", [agent])
        run_tracked_proc(app, app.tracked_procs[0])

    mock_persist.assert_called_once_with(agent, "hook", [agent])
    mock_save.assert_not_called()
    assert app.refresh_schedules == 1
    assert app._notifications == [("Kill cleanup failed: boom", "error")]
    assert app._kill_persistence_inflight == set()
