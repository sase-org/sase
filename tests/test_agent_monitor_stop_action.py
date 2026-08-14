"""Tests for the monitor-stop flow reached through the agent-kill key."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents import AgentsMixin
from sase.ace.tui.models.agent import Agent, AgentType
from tests._agent_kill_single_helpers import cleanup_plan


class _ActionApp(AgentsMixin):
    def __init__(self, agent: Agent) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = [agent]
        self._agents_with_children = [agent]
        self._marked_agents = set()
        self._current_group_key = None
        self._notifications: list[tuple[str, str]] = []
        self.pushed: list[tuple[object, Callable[[bool], None]]] = []
        self.submitted: list[tuple[object, ...]] = []

    def notify(self, msg: str, severity: str = "information") -> None:
        self._notifications.append((msg, severity))

    def push_screen(self, modal: object, callback: Callable[[bool], None]) -> None:
        self.pushed.append((modal, callback))

    def _get_selected_agent(self) -> Agent | None:
        return self._agents[self.current_idx] if self._agents else None

    def _submit_proc(self, *args: object, **kwargs: object) -> bool:
        self.submitted.append(args)
        return True


def _monitor_agent(*, artifacts_dir: str, monitor_state: str = "running") -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-row",
        project_file="/tmp/project/monitor.sase",
        status="MONITORING",
        start_time=None,
        artifacts_dir=artifacts_dir,
        agent_name="alpha--mon",
        agent_family="alpha",
        agent_family_role="monitor",
        role_suffix="--mon",
        monitor_id="m123",
        monitor_state=monitor_state,
        monitor_command="just check-full",
        monitor_label="just check",
    )
    assert agent.is_monitor is True
    return agent


def _monitor_starter_agent(*, artifacts_dir: str) -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="starter-row",
        project_file="/tmp/project/monitor.sase",
        status="DONE",
        start_time=None,
        artifacts_dir=artifacts_dir,
        raw_suffix="starter-12345",
        agent_name="alpha--0",
        agent_family="alpha",
        agent_family_role="root",
        role_suffix="--0",
        monitor_id="m123",
    )
    assert agent.is_monitor is False
    return agent


def test_action_kill_agent_on_running_monitor_pushes_confirm_modal(
    tmp_path: Path,
) -> None:
    agent = _monitor_agent(artifacts_dir=str(tmp_path), monitor_state="running")
    app = _ActionApp(agent)

    app.action_kill_agent()

    assert len(app.pushed) == 1
    assert app.submitted == []


def test_action_kill_agent_on_terminal_monitor_uses_cleanup_path(
    tmp_path: Path,
) -> None:
    agent = _monitor_agent(artifacts_dir=str(tmp_path), monitor_state="completed")
    app = _ActionApp(agent)
    plan = cleanup_plan(agent, action="dismiss")

    with (
        patch("sase.core.agent_cleanup_facade.plan_agent_cleanup", return_value=plan),
        patch.object(app, "_dismiss_planned_agent") as mock_dismiss,
    ):
        app.action_kill_agent()

    mock_dismiss.assert_called_once_with(agent, plan)
    assert app.pushed == []
    assert app._notifications == []


def test_action_kill_agent_on_done_monitor_starter_uses_cleanup_path(
    tmp_path: Path,
) -> None:
    agent = _monitor_starter_agent(artifacts_dir=str(tmp_path))
    app = _ActionApp(agent)
    plan = cleanup_plan(agent, action="dismiss")

    with (
        patch("sase.core.agent_cleanup_facade.plan_agent_cleanup", return_value=plan),
        patch.object(app, "_dismiss_planned_agent") as mock_dismiss,
    ):
        app.action_kill_agent()

    mock_dismiss.assert_called_once_with(agent, plan)
    assert app.pushed == []
    assert ("Monitor has already finished", "warning") not in app._notifications


def test_confirming_stop_submits_background_task(tmp_path: Path) -> None:
    agent = _monitor_agent(artifacts_dir=str(tmp_path), monitor_state="running")
    app = _ActionApp(agent)

    app.action_kill_agent()
    assert len(app.pushed) == 1
    _modal, callback = app.pushed[0]
    callback(True)

    assert len(app.submitted) == 1
    proc_type, dedup_key, project_file, _task_callable = app.submitted[0]
    assert proc_type == "monitor-stop"
    assert dedup_key == "alpha--mon"
    assert project_file == "/tmp/project/monitor.sase"


def test_declining_confirm_does_not_submit(tmp_path: Path) -> None:
    agent = _monitor_agent(artifacts_dir=str(tmp_path), monitor_state="running")
    app = _ActionApp(agent)

    app.action_kill_agent()
    _modal, callback = app.pushed[0]
    callback(False)

    assert app.submitted == []


def test_stop_monitor_task_callable_stops_and_reports_success(
    tmp_path: Path,
) -> None:
    agent = _monitor_agent(artifacts_dir=str(tmp_path), monitor_state="running")
    app = _ActionApp(agent)

    app.action_kill_agent()
    _modal, callback = app.pushed[0]
    callback(True)
    _task_type, _dedup_key, _project_file, proc_callable = app.submitted[0]
    assert callable(proc_callable)

    fake_record = object()
    fake_updated = type("Rec", (), {"monitor_state": "stopped"})()
    with (
        patch("sase.monitor.store.get_monitor", return_value=fake_record) as mock_get,
        patch(
            "sase.monitor.store.stop_monitor", return_value=fake_updated
        ) as mock_stop,
    ):
        success, message = proc_callable()  # type: ignore[operator]

    mock_get.assert_called_once_with("project", str(tmp_path))
    mock_stop.assert_called_once_with(fake_record)
    assert success is True
    assert "Stopped" in message
    assert "stopped" in message


def test_stop_monitor_task_callable_reports_missing_record(tmp_path: Path) -> None:
    agent = _monitor_agent(artifacts_dir=str(tmp_path), monitor_state="running")
    app = _ActionApp(agent)

    app.action_kill_agent()
    _modal, callback = app.pushed[0]
    callback(True)
    _task_type, _dedup_key, _project_file, proc_callable = app.submitted[0]
    assert callable(proc_callable)

    with patch("sase.monitor.store.get_monitor", return_value=None):
        success, message = proc_callable()  # type: ignore[operator]

    assert success is False
    assert "not found" in message
