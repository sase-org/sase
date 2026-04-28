"""Tests for `_do_kill_agent` (single-agent kill flow)."""

from __future__ import annotations

import asyncio

from unittest.mock import patch

from sase.ace.tui.models.agent import Agent, AgentType


def test_do_kill_agent_removes_in_memory_before_background_persistence() -> None:
    """Kill path should update UI state immediately and defer persistence work."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
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

        def _schedule_agents_async_refresh(self) -> None:
            return

    app = MockApp()
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
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
    assert len(app._scheduled) == 1
    callback, args = app._scheduled[0]
    assert callback == app._run_kill_persistence_async
    assert args[0] == agent


def test_do_kill_agent_hook_persistence_runs_async() -> None:
    """Hook project-file writes are deferred to async persistence stage."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
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

        def _schedule_agents_async_refresh(self) -> None:
            return

    app = MockApp()
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
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
        callback, args = app._scheduled[0]
        asyncio.run(callback(*args))  # type: ignore[misc]
        mock_persist_hook.assert_called_once_with(agent)


def test_run_kill_persistence_does_not_refresh_on_success() -> None:
    """Successful cleanup should not schedule a redundant full agent reload."""
    from sase.ace.tui.actions.agents import AgentsMixin

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []
            self._kill_persistence_inflight = set()
            self._dismissed_agents = set()
            self._agents_with_children = []
            self.refresh_schedules = 0
            self.async_count_refreshes = 0

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _schedule_agents_async_refresh(self) -> None:
            self.refresh_schedules += 1

        async def _refresh_notification_count_async(self) -> None:
            self.async_count_refreshes += 1

    app = MockApp()
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
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
        asyncio.run(app._run_kill_persistence_async(agent, "hook", [agent]))

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

    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []
            self._kill_persistence_inflight = set()
            self._dismissed_agents = set()
            self._agents_with_children = []
            self.refresh_schedules = 0
            self.async_count_refreshes = 0

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _schedule_agents_async_refresh(self) -> None:
            self.refresh_schedules += 1

        async def _refresh_notification_count_async(self) -> None:
            self.async_count_refreshes += 1

    app = MockApp()
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.gp",
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
        asyncio.run(app._run_kill_persistence_async(agent, "hook", [agent]))

    mock_persist.assert_called_once_with(agent, "hook", [agent])
    mock_save.assert_not_called()
    assert app.refresh_schedules == 1
    assert app._notifications == [("Kill cleanup failed for my_feature: boom", "error")]
    assert app._kill_persistence_inflight == set()
