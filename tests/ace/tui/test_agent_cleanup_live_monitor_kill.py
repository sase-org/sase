"""Bulk and focused cleanup must stop live monitors without killpg."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents import AgentsMixin
from sase.ace.tui.models.agent import Agent, AgentType
from tests._agent_cleanup_proc_helpers import TrackedProcRecorderMixin


def _owner() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase-ru.6",
        project_file="/tmp/project.sase",
        status="DONE",
        start_time=datetime(2026, 8, 22, 4, 0, 0),
        stop_time=datetime(2026, 8, 22, 4, 30, 0),
        raw_suffix="owner-ts",
        pid=None,
        agent_name="sase-ru.6",
    )


def _monitor() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase-ru.6--mon-1",
        project_file="/tmp/project.sase",
        status="MONITORING",
        start_time=datetime(2026, 8, 22, 4, 45, 0),
        raw_suffix="mon-ts",
        parent_timestamp="owner-ts",
        pid=1665545,
        agent_name="sase-ru.6--mon-1",
        agent_family="sase-ru.6",
        agent_family_role="monitor",
        role_suffix="--mon-1",
        monitor_id="0fmbm91hgytw",
        monitor_state="running",
    )


class _App(TrackedProcRecorderMixin, AgentsMixin):
    def __init__(self, agents: list[Agent]) -> None:
        self._init_tracked_task_recorder()
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self._dismissed_agents = set()
        self._marked_agents = set()
        self._kill_persistence_inflight = set()
        self._agent_status_overrides: dict[Any, Any] = {}
        self._agent_pre_question_status: dict[Any, Any] = {}
        self.notifications: list[tuple[str, str]] = []
        self.signaled: list[int] = []
        self.cleanup_payloads: list[dict[str, Any]] = []

    def notify(
        self, message: str, severity: str = "information", **_kwargs: object
    ) -> None:
        self.notifications.append((message, severity))

    def _kill_agent_process_group(self, agent: Agent) -> bool:
        if agent.pid is not None:
            self.signaled.append(agent.pid)
        return True

    def _capture_focused_visible_pos(self) -> None:
        return None

    def _try_remove_agent_rows(self, _identities: set[Any]) -> bool:
        return False

    def _restore_focus_after_removal(self, _prior: object) -> None:
        return None

    def _refresh_agents_display(self, **_kwargs: object) -> None:
        return None

    def _reset_marked_agents(self) -> None:
        self._marked_agents = set()

    def _append_dismissed_agent_objects(
        self, _agents: list[Agent], _ids: set[Any]
    ) -> None:
        return None

    def _notify_after_refresh(self, message: str) -> None:
        self.notifications.append((message, "information"))

    def _submit_cleanup_proc(self, **kwargs: Any) -> bool:
        payload = kwargs.get("payload")
        if isinstance(payload, dict):
            self.cleanup_payloads.append(payload)
        on_settled = kwargs.get("on_settled")
        if callable(on_settled):
            on_settled()
        return True


def test_bulk_cleanup_does_not_signal_monitor_supervisor_pid() -> None:
    owner = _owner()
    monitor = _monitor()
    app = _App([owner, monitor])

    app._do_bulk_kill_agents([monitor], [owner])

    assert app.signaled == []
    assert app.cleanup_payloads
    payload = app.cleanup_payloads[0]
    assert payload["transaction"] == "bulk_kill"
    assert "monitor" in [item["kind"] for item in payload["kill_items"]]
    plan = payload["cleanup_plan"]
    assert plan["kill_items"][0]["kind"] == "monitor"
    assert plan["kill_items"][0]["monitor_id"] == "0fmbm91hgytw"
    assert plan["kill_items"][0]["pid"] is None
    assert plan["side_effects"]["monitor_stop_requests"][0]["monitor_id"] == (
        "0fmbm91hgytw"
    )


def test_focused_owner_kill_includes_cascaded_monitor_without_killpg() -> None:
    owner = _owner()
    monitor = _monitor()
    app = _App([owner, monitor])
    from sase.ace.tui.actions.agents._kill_cleanup_planning import (
        plan_single_agent_kill_cleanup,
    )

    plan = plan_single_agent_kill_cleanup(owner, [owner, monitor])
    app._do_kill_agent(owner, plan)

    assert app.signaled == []
    assert app.cleanup_payloads
    plan_payload = app.cleanup_payloads[0]["cleanup_plan"]
    assert any(item["kind"] == "monitor" for item in plan_payload["kill_items"])
    assert plan_payload["side_effects"]["monitor_stop_requests"][0]["monitor_id"] == (
        "0fmbm91hgytw"
    )


def test_generic_signal_helper_is_not_used_for_monitor_kind() -> None:
    monitor = _monitor()
    app = _App([monitor])
    from sase.ace.tui.actions.agents._kill_cleanup_planning import (
        plan_single_agent_kill_cleanup,
    )

    plan = plan_single_agent_kill_cleanup(monitor, [monitor])
    with patch.object(app, "_kill_process_group") as kill_pg:
        app._do_kill_agent(monitor, plan)
    kill_pg.assert_not_called()
    assert app.signaled == []
