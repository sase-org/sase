"""Phase 1 (TUI Performance v2) regression tests.

Verifies that ``_do_kill_agent`` / ``_do_bulk_kill_agents`` do no
notification or dismissed-set disk I/O on the immediate (UI-thread) stage,
and that the per-kill persistence worker performs the I/O off the main
thread and refreshes the notification indicator asynchronously.

See ``sdd/plans/202604/tui_perf_v2.md`` (Phase 1).
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from sase.ace.tui.models.agent import Agent, AgentType


def _make_running_agent(cl_name: str = "feature_one", pid: int = 111) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        pid=pid,
        raw_suffix=f"fix_hook-{pid}-251230_151429",
    )


def test_kill_immediate_does_no_notification_io() -> None:
    """The kill immediate (UI-thread) stage must not touch notifications/dismissed-set storage."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []
            self.current_tab = "agents"
            self.current_idx = 0
            self._kill_persistence_inflight = set()
            self._agent_status_overrides = {}
            self._agent_pre_question_status = {}
            self._dismissed_agents = set()
            self._agents_with_children = []
            self._agents = []
            self._scheduled: list[tuple[object, tuple[object, ...]]] = []
            self.refresh_count_calls = 0

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _refresh_notification_count(self) -> None:
            self.refresh_count_calls += 1

        def _refresh_agents_display(
            self, *, list_changed: bool = False, defer_detail: bool = False
        ) -> None:
            return

        def call_later(self, callback: object, *args: object) -> None:
            self._scheduled.append((callback, args))

        def _schedule_agents_async_refresh(self) -> None:
            return

    app = MockApp()
    agent = _make_running_agent()
    app._agents = [agent]
    app._agents_with_children = [agent]

    with (
        patch("sase.ace.tui.actions.agents._killing.os.killpg"),
        patch("sase.notifications.load_notifications") as mock_load_notifs,
        patch("sase.notifications.mark_dismissed") as mock_mark_dismissed,
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save_dismissed,
        patch("sase.ace.changespec.parse_project_file") as mock_parse_project,
        patch(
            "sase.ace.tui.actions.agents._killing_utils.delete_agent_artifacts"
        ) as mock_delete_artifacts,
    ):
        app._do_kill_agent(agent)

    mock_load_notifs.assert_not_called()
    mock_mark_dismissed.assert_not_called()
    mock_save_dismissed.assert_not_called()
    mock_parse_project.assert_not_called()
    mock_delete_artifacts.assert_not_called()
    # The synchronous notification-count indicator refresh must be removed
    # from the immediate path (it loaded notifications from disk).
    assert app.refresh_count_calls == 0


def test_kill_schedules_one_persistence_task() -> None:
    """One ``_run_kill_persistence_async`` task per ``_do_kill_agent``; agent removed before worker runs."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []
            self.current_tab = "agents"
            self.current_idx = 0
            self._kill_persistence_inflight = set()
            self._agent_status_overrides = {}
            self._agent_pre_question_status = {}
            self._dismissed_agents = set()
            self._agents_with_children = []
            self._agents = []
            self._scheduled: list[tuple[object, tuple[object, ...]]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _refresh_notification_count(self) -> None:
            return

        def _refresh_agents_display(
            self, *, list_changed: bool = False, defer_detail: bool = False
        ) -> None:
            return

        def call_later(self, callback: object, *args: object) -> None:
            self._scheduled.append((callback, args))

        def _schedule_agents_async_refresh(self) -> None:
            return

    app = MockApp()
    agent = _make_running_agent()
    app._agents = [agent]
    app._agents_with_children = [agent]

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_kill_agent(agent)

    # Agent gone from the in-memory list before any worker runs.
    assert app._agents == []
    # Exactly one persistence task scheduled.
    persistence_calls = [
        c for c, _ in app._scheduled if c == app._run_kill_persistence_async
    ]
    assert len(persistence_calls) == 1


def test_kill_persistence_refreshes_count_async() -> None:
    """``_refresh_notification_count_async`` is awaited exactly once per successful worker run."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []
            self._kill_persistence_inflight = set()
            self._dismissed_agents = set()
            self._agents_with_children = []
            self.refresh_schedules = 0
            self.async_count_refreshes = 0
            self.sync_count_refreshes = 0

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _schedule_agents_async_refresh(self) -> None:
            self.refresh_schedules += 1

        def _refresh_notification_count(self) -> None:
            self.sync_count_refreshes += 1

        async def _refresh_notification_count_async(self) -> None:
            self.async_count_refreshes += 1

    app = MockApp()
    agent = _make_running_agent()
    app._dismissed_agents = {agent.identity}

    with (
        patch("sase.ace.tui.actions.agents._killing.persist_kill_side_effects"),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.tui.actions.agents._killing.dismiss_notifications_for_agents"),
    ):
        asyncio.run(
            app._run_kill_persistence_async(agent, "running", [agent], {agent.identity})
        )

    assert app.async_count_refreshes == 1
    # The synchronous version (which would block on disk I/O) must not be used.
    assert app.sync_count_refreshes == 0


def test_kill_persistence_uses_captured_dismissed_snapshot() -> None:
    """Worker writes the snapshot captured on the UI thread, not a fresh read."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []
            self._kill_persistence_inflight = set()
            self._dismissed_agents = set()
            self._agents_with_children = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _schedule_agents_async_refresh(self) -> None:
            return

        async def _refresh_notification_count_async(self) -> None:
            return

    app = MockApp()
    agent = _make_running_agent()
    snapshot = {agent.identity}
    # Mutate ``_dismissed_agents`` after the snapshot to verify the worker
    # uses the snapshot rather than re-reading the live set.
    other = _make_running_agent(cl_name="other", pid=222)
    app._dismissed_agents = {agent.identity, other.identity}

    with (
        patch("sase.ace.tui.actions.agents._killing.persist_kill_side_effects"),
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
        patch("sase.ace.tui.actions.agents._killing.dismiss_notifications_for_agents"),
    ):
        asyncio.run(
            app._run_kill_persistence_async(agent, "running", [agent], snapshot)
        )

    mock_save.assert_called_once_with(snapshot)


def test_bulk_kill_no_sync_count_refresh() -> None:
    """``_do_bulk_kill_agents`` must not synchronously refresh the notification count."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
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
            self.refresh_count_calls = 0

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _refresh_notification_count(self) -> None:
            self.refresh_count_calls += 1

        def _refresh_agents_display(
            self, *, list_changed: bool = False, defer_detail: bool = False
        ) -> None:
            return

        def call_later(self, callback: object, *args: object) -> None:
            self._scheduled.append((callback, args))

        def _schedule_agents_async_refresh(self) -> None:
            return

    app = MockApp()
    a1 = _make_running_agent(cl_name="feature_one", pid=111)
    a2 = _make_running_agent(cl_name="feature_two", pid=222)
    app._agents = [a1, a2]
    app._agents_with_children = [a1, a2]

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_bulk_kill_agents([a1, a2])

    assert app.refresh_count_calls == 0


def test_bulk_kill_persistence_refreshes_count_async() -> None:
    """The bulk-kill worker awaits ``_refresh_notification_count_async`` once on success."""
    from sase.ace.tui.actions.agents import AgentsMixin
    from sase.ace.tui.actions.agents._kill_persistence import BulkKillItem

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []
            self._kill_persistence_inflight = set()
            self.refresh_schedules = 0
            self.async_count_refreshes = 0

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _schedule_agents_async_refresh(self) -> None:
            self.refresh_schedules += 1

        async def _refresh_notification_count_async(self) -> None:
            self.async_count_refreshes += 1

    app = MockApp()
    agent = _make_running_agent()
    item = BulkKillItem(agent=agent, kind="running", identities={agent.identity})

    with patch("sase.ace.tui.actions.agents._killing.persist_bulk_kill_side_effects"):
        asyncio.run(
            app._run_bulk_kill_persistence_async([item], [], {agent.identity}, [agent])
        )

    assert app.async_count_refreshes == 1
