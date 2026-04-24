"""Tests for `_do_bulk_kill_agents` (multi-agent kill flow)."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.models.agent import Agent, AgentType


def test_do_bulk_kill_agents_refreshes_and_schedules_once() -> None:
    """Bulk kill should remove all rows immediately with one refresh/task."""
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
            self._pinned_agents = set()
            self._marked_agents = set()
            self._agents_with_children = []
            self._agents = []
            self._main_panel_indices = []
            self._pinned_panel_indices = []
            self._pinned_panel_focused = "main"
            self._scheduled: list[tuple[object, tuple[object, ...]]] = []
            self.refresh_calls: list[tuple[bool, bool]] = []
            self.notification_refreshes = 0

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _refresh_notification_count(self) -> None:
            self.notification_refreshes += 1

        def _build_panel_indices(self) -> None:
            self._main_panel_indices = list(range(len(self._agents)))
            self._pinned_panel_indices = []

        def _active_panel_indices(self) -> list[int]:
            return self._main_panel_indices

        def _refresh_agents_display(
            self, *, list_changed: bool = False, defer_detail: bool = False
        ) -> None:
            self.refresh_calls.append((list_changed, defer_detail))

        def call_later(self, callback: object, *args: object) -> None:
            self._scheduled.append((callback, args))

        def _schedule_agents_async_refresh(self) -> None:
            return

    app = MockApp()
    a1 = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature_one",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        pid=111,
        raw_suffix="fix_hook-111-251230_151429",
    )
    a2 = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature_two",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="mentor",
        pid=222,
        raw_suffix="mentor_complete-222-251230_151429",
    )
    app._agents = [a1, a2]
    app._agents_with_children = [a1, a2]
    app._marked_agents = {a1.identity, a2.identity}

    with patch("sase.ace.tui.actions.agents._killing.os.killpg") as mock_killpg:
        app._do_bulk_kill_agents([a1, a2])

    assert [call.args[0] for call in mock_killpg.call_args_list] == [111, 222]
    assert app._agents == []
    assert app._agents_with_children == []
    assert app._marked_agents == set()
    assert a1.identity in app._dismissed_agents
    assert a2.identity in app._dismissed_agents
    assert app.refresh_calls == [(True, True)]
    assert app.notification_refreshes == 1
    assert len(app._scheduled) == 1
    callback, args = app._scheduled[0]
    assert callback == app._run_bulk_kill_persistence_async
    assert len(args[0]) == 2


def test_do_bulk_kill_agents_removes_workflow_children_immediately() -> None:
    """Killing a workflow parent should hide its step rows in the same refresh."""
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
            self._pinned_agents = set()
            self._marked_agents = set()
            self._agents_with_children = []
            self._agents = []
            self._main_panel_indices = []
            self._pinned_panel_indices = []
            self._pinned_panel_focused = "main"
            self._scheduled: list[tuple[object, tuple[object, ...]]] = []
            self.refresh_calls: list[tuple[bool, bool]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _refresh_notification_count(self) -> None:
            return

        def _build_panel_indices(self) -> None:
            self._main_panel_indices = list(range(len(self._agents)))
            self._pinned_panel_indices = []

        def _active_panel_indices(self) -> list[int]:
            return self._main_panel_indices

        def _refresh_agents_display(
            self, *, list_changed: bool = False, defer_detail: bool = False
        ) -> None:
            self.refresh_calls.append((list_changed, defer_detail))

        def call_later(self, callback: object, *args: object) -> None:
            self._scheduled.append((callback, args))

        def _schedule_agents_async_refresh(self) -> None:
            return

    app = MockApp()
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="feature",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="wf",
        pid=333,
        raw_suffix="20240101120000",
    )
    child = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="step",
        project_file="/tmp/test.gp",
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

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_bulk_kill_agents([parent])

    assert app._agents == []
    assert app._agents_with_children == []
    assert parent.identity in app._dismissed_agents
    assert child.identity in app._dismissed_agents
    assert app.refresh_calls == [(True, True)]


def test_do_bulk_kill_agents_failed_pid_stays_visible() -> None:
    """A failed process-group kill should not remove that agent."""
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
            self._pinned_agents = set()
            self._marked_agents = set()
            self._agents_with_children = []
            self._agents = []
            self._main_panel_indices = []
            self._pinned_panel_indices = []
            self._pinned_panel_focused = "main"
            self._scheduled: list[tuple[object, tuple[object, ...]]] = []
            self.refresh_calls: list[tuple[bool, bool]] = []

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _refresh_notification_count(self) -> None:
            return

        def _build_panel_indices(self) -> None:
            self._main_panel_indices = list(range(len(self._agents)))
            self._pinned_panel_indices = []

        def _active_panel_indices(self) -> list[int]:
            return self._main_panel_indices

        def _refresh_agents_display(
            self, *, list_changed: bool = False, defer_detail: bool = False
        ) -> None:
            self.refresh_calls.append((list_changed, defer_detail))

        def call_later(self, callback: object, *args: object) -> None:
            self._scheduled.append((callback, args))

        def _schedule_agents_async_refresh(self) -> None:
            return

    app = MockApp()
    failed = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="failed",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        pid=111,
        raw_suffix="fix_hook-111-251230_151429",
    )
    killed = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="killed",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=None,
        workflow="mentor",
        pid=222,
        raw_suffix="mentor_complete-222-251230_151429",
    )
    app._agents = [failed, killed]
    app._agents_with_children = [failed, killed]

    def fake_killpg(pid: int, sig: int) -> None:
        if pid == 111:
            raise PermissionError

    with patch(
        "sase.ace.tui.actions.agents._killing.os.killpg", side_effect=fake_killpg
    ):
        app._do_bulk_kill_agents([failed, killed])

    assert app._agents == [failed]
    assert app._agents_with_children == [failed]
    assert failed.identity not in app._dismissed_agents
    assert killed.identity in app._dismissed_agents
    assert app.refresh_calls == [(True, True)]
