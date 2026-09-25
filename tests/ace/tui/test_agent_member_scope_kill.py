"""Focused and bulk x must stop every member kind in one step."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents import AgentsMixin
from sase.ace.tui.actions.agents._marking_kill import _leftover_cleanup_line
from sase.ace.tui.models.agent import Agent, AgentType

_NOW = datetime(2026, 8, 23, 12, 0, 0)


def _monitor() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase-ru.6--mon-1",
        project_file="/tmp/project.sase",
        status="MONITORING",
        start_time=_NOW,
        raw_suffix="mon-ts",
        parent_timestamp="owner-ts",
        pid=1665545,
        agent_name="sase-ru.6--mon-1",
        agent_session="sase-ru.6",
        agent_session_role="monitor",
        role_suffix="--mon-1",
        monitor_id="0fmbm91hgytw",
        monitor_state="running",
    )


def _proc_shell(*, proc_id: str = "abc123def456", active: bool = True) -> Agent:
    return Agent(
        agent_type=AgentType.PROC_SHELL,
        cl_name="sase",
        project_file="",
        status="RUNNING" if active else "DONE",
        start_time=_NOW,
        raw_suffix=proc_id,
        proc_id=proc_id,
        proc_status="running" if active else "success",
        proc_label="unit-1",
        agent_name="unit-1",
        agent_clan="alpha",
        agent_clan_generation="gen",
    )


def _gate(*, state: str = "pending") -> Agent:
    status = "GATED" if state == "pending" else "GATE DONE"
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="gate",
        project_file="/tmp/test.sase",
        status=status,
        start_time=_NOW,
        raw_suffix="20260823130000",
        agent_name="gate",
        agent_clan="alpha",
        agent_clan_generation="gen",
    )
    agent.agent_session_role = "gate"
    agent.role_suffix = "--gate"
    agent.gate_id = "gate-abc123"
    agent.gate_kind = "approval"
    agent.gate_state = state
    assert agent.is_gate is True
    return agent


def _done_member() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha.done",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=_NOW,
        stop_time=_NOW,
        raw_suffix="alpha-done",
        agent_name="alpha.done",
        agent_clan="alpha",
        agent_clan_generation="gen",
    )


def _clan_container() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=_NOW,
        raw_suffix=None,
        agent_name="alpha",
        agent_clan="alpha",
        agent_clan_generation="gen",
        is_clan_container=True,
    )


class _App(AgentsMixin):  # type: ignore[misc]
    def __init__(self, agents: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self._dismissed_agents: set[Any] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._dismissed_proc_shells: set[str] = set()
        self._marked_agents: set[Any] = set()
        self._kill_persistence_inflight: set[Any] = set()
        self._dismiss_persistence_inflight: set[Any] = set()
        self._agent_status_overrides: dict[Any, Any] = {}
        self._explicit_removals: set[Any] = set()
        self._explicit_removal_suffixes: set[str] = set()
        self._explicit_removal_cl_suffixes: set[tuple[str, str]] = set()
        self._agents_removal_generation = 0
        self._current_group_key = None
        self.notifications: list[tuple[str, str]] = []
        self.pushed: list[tuple[Any, Any]] = []
        self.cleanup_payloads: list[dict[str, Any]] = []
        self.signaled: list[int] = []
        self.auto_confirm = True

    def notify(
        self, message: str, severity: str = "information", **_kwargs: Any
    ) -> None:
        self.notifications.append((message, severity))

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed.append((modal, callback))
        if self.auto_confirm and callable(callback):
            callback(True)

    def _get_selected_agent(self) -> Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def _kill_agent_process_group(self, agent: Agent) -> bool:
        if agent.pid is not None:
            self.signaled.append(agent.pid)
        return True

    def _capture_focused_visible_pos(self) -> None:
        return None

    def _try_remove_agent_rows(self, _identities: set[Any]) -> bool:
        return False

    def _restore_focus_after_removal(self, _prior: Any) -> None:
        return None

    def _refresh_agents_display(self, **_kwargs: Any) -> None:
        return None

    def _refilter_agents(self, **_kwargs: Any) -> None:
        self._agents = self.filter_explicitly_removed(self._agents_with_children)

    def _reset_marked_agents(self) -> None:
        self._marked_agents = set()

    def _append_dismissed_agent_objects(
        self, agents: list[Agent], _ids: set[Any]
    ) -> None:
        self._dismissed_agent_objects.extend(agents)

    def _notify_after_refresh(
        self, message: str, severity: str = "information"
    ) -> None:
        self.notifications.append((message, severity))

    def _schedule_agents_async_refresh(self, **_kwargs: Any) -> None:
        return None

    def _submit_cleanup_proc(self, **kwargs: Any) -> bool:
        payload = kwargs.get("payload")
        if isinstance(payload, dict):
            self.cleanup_payloads.append(payload)
        on_settled = kwargs.get("on_settled")
        if callable(on_settled):
            on_settled()
        return True


def test_focused_x_on_running_monitor_removes_row_in_one_step() -> None:
    monitor = _monitor()
    app = _App([monitor])

    app.action_kill_agent()

    assert len(app.pushed) == 1
    assert app.pushed[0][0].__class__.__name__ == "ConfirmStopMonitorModal"
    assert [a.identity for a in app._agents_with_children] == []
    assert monitor.identity in app._explicit_removals
    assert app.signaled == []
    assert len(app.cleanup_payloads) == 1
    payload = app.cleanup_payloads[0]
    assert payload["transaction"] == "single_kill"
    assert payload["kind"] == "monitor"


def test_focused_x_on_active_proc_shell_removes_row_in_one_step() -> None:
    shell = _proc_shell()
    app = _App([shell])

    app.action_kill_agent()

    assert len(app.pushed) == 1
    assert app.pushed[0][0].__class__.__name__ == "ConfirmKillProcShellModal"
    assert [a.identity for a in app._agents_with_children] == []
    assert shell.identity in app._explicit_removals
    assert shell.proc_id in app._dismissed_proc_shells
    assert len(app.cleanup_payloads) == 1
    payload = app.cleanup_payloads[0]
    assert payload["transaction"] == "bulk_kill"
    from sase.ace.tui.actions.cleanup_payload import agents_from_json

    stopped = agents_from_json(payload["proc_stops"])
    assert [agent.proc_id for agent in stopped] == [shell.proc_id]
    assert agents_from_json(payload["gate_cancels"]) == []


def test_focused_x_on_pending_gate_removes_row_in_one_step() -> None:
    gate = _gate()
    app = _App([gate])

    app.action_kill_agent()

    assert len(app.pushed) == 1
    assert app.pushed[0][0].__class__.__name__ == "ConfirmCancelGateModal"
    assert [a.identity for a in app._agents_with_children] == []
    assert gate.identity in app._explicit_removals
    assert len(app.cleanup_payloads) == 1
    payload = app.cleanup_payloads[0]
    assert payload["transaction"] == "bulk_kill"
    from sase.ace.tui.actions.cleanup_payload import agents_from_json

    cancelled = agents_from_json(payload["gate_cancels"])
    assert [agent.gate_id for agent in cancelled] == [gate.gate_id]
    assert agents_from_json(payload["proc_stops"]) == []


def test_focused_x_on_settling_gate_keeps_warning() -> None:
    gate = _gate()
    gate.gate_state = "settling"
    app = _App([gate])

    app.action_kill_agent()

    assert app.pushed == []
    assert app.cleanup_payloads == []
    assert [a.identity for a in app._agents_with_children] == [gate.identity]
    assert ("Gate is waiting for a decision", "warning") in app.notifications


def test_clan_kill_with_proc_shell_and_gate_removes_container() -> None:
    from sase.ace.tui.models._agent_tree import project_clan_tree

    done = _done_member()
    shell = _proc_shell()
    gate = _gate()
    roster = project_clan_tree([done, shell, gate])
    container = next(a for a in roster if a.is_clan_container)
    app = _App(roster)
    app.current_idx = app._agents.index(container)

    app.action_kill_agent()

    assert len(app.pushed) == 1
    description = app.pushed[0][0].agent_description
    assert "Kill 1 running proc shell" in description
    assert "Cancel 1 gate" in description
    assert "Skipping" not in description
    remaining = {a.identity for a in app._agents_with_children}
    assert remaining == set()
    assert shell.identity in app._explicit_removals
    assert gate.identity in app._explicit_removals
    assert len(app.cleanup_payloads) == 1
    payload = app.cleanup_payloads[0]
    assert payload["transaction"] == "bulk_kill"
    from sase.ace.tui.actions.cleanup_payload import agents_from_json

    assert [a.proc_id for a in agents_from_json(payload["proc_stops"])] == [
        shell.proc_id
    ]
    assert [a.gate_id for a in agents_from_json(payload["gate_cancels"])] == [
        gate.gate_id
    ]


def test_agent_by_identity_resolves_folded_remote_member() -> None:
    visible = _done_member()
    folded = _gate()
    folded.fleet_origin_alias = "remote-host"
    app = _App([visible])
    app._agents_with_children = [visible, folded]

    assert app._agent_by_identity(folded.identity) is folded
    assert app._agent_by_identity(visible.identity) is visible
    assert app._agent_by_identity((AgentType.RUNNING, "nope", None)) is None


def test_durable_bulk_transaction_runs_member_intents(monkeypatch: Any) -> None:
    import sase.ace.dismissed_agents as dismissed_agents
    import sase.ace.tui.actions.agents._kill_member_intents as intents
    from sase.ace.tui.actions.agents._kill_transactions import (
        persist_bulk_kill_transaction,
    )

    shell = _proc_shell()
    gate = _gate()
    stopped: list[list[Agent]] = []
    cancelled: list[list[Agent]] = []
    monkeypatch.setattr(
        dismissed_agents, "save_dismissed_agents", lambda snapshot: True
    )
    monkeypatch.setattr(
        intents,
        "execute_proc_stop_intents",
        lambda agents: stopped.append(list(agents)) or set(),
    )
    monkeypatch.setattr(
        intents,
        "execute_gate_cancel_intents",
        lambda agents: cancelled.append(list(agents)) or set(),
    )

    persist_bulk_kill_transaction(
        [],
        [],
        set(),
        [shell, gate],
        None,
        None,
        [shell],
        [gate],
    )

    assert stopped == [[shell]]
    assert cancelled == [[gate]]


def test_durable_member_stop_failure_reports_resurface(monkeypatch: Any) -> None:
    import sase.ace.dismissed_agents as dismissed_agents
    import sase.ace.tui.actions.agents._kill_member_intents as intents
    from sase.ace.tui.actions.agents._kill_member_intents import MemberStopError
    from sase.ops.commands._agent_cleanup import apply_cleanup_payload_for_result

    gate = _gate()
    monkeypatch.setattr(
        dismissed_agents, "save_dismissed_agents", lambda snapshot: True
    )

    def _fail(_agents: list[Agent]) -> set[Any]:
        raise MemberStopError("nope", resurface_identities={gate.identity})

    monkeypatch.setattr(intents, "execute_proc_stop_intents", lambda agents: set())
    monkeypatch.setattr(intents, "execute_gate_cancel_intents", _fail)

    from sase.ace.tui.actions.cleanup_payload import (
        json_identities,
        serialize_agents,
    )

    ok, _message, result = apply_cleanup_payload_for_result(
        {
            "action": "kill",
            "transaction": "bulk_kill",
            "dismissed_identities": [],
            "agents_with_children": serialize_agents([gate]),
            "cleanup_plan": None,
            "kill_items": [],
            "dismissable": [],
            "proc_stops": [],
            "gate_cancels": serialize_agents([gate]),
            "recent_group": None,
        }
    )

    assert ok is False
    assert result["severity"] == "error"
    assert result["schedule_agents_refresh_source"] == "kill_error_recovery"
    assert result["resurface_identities"] == json_identities({gate.identity})


def test_cleanup_completion_resurfaces_failed_members() -> None:
    gate = _gate()
    app = _App([gate])
    app._dismissed_agents.add(gate.identity)
    app.record_explicit_removals({gate.identity})

    from sase.ace.tui.actions.cleanup_payload import json_identities

    completion = SimpleNamespace(
        payload={
            "message": "Kill cleanup failed: nope",
            "notify": True,
            "severity": "error",
            "schedule_agents_refresh_source": "kill_error_recovery",
            "resurface_identities": json_identities({gate.identity}),
        },
        success=False,
        message="Kill cleanup failed: nope",
    )
    app._on_cleanup_proc_complete(completion)  # type: ignore[arg-type]

    assert gate.identity not in app._explicit_removals
    assert gate.identity not in app._dismissed_agents
    assert app._schedule_agents_async_refresh is not None


def test_leftover_cleanup_line_names_uncovered_rows() -> None:
    line = _leftover_cleanup_line([_done_member()], [_done_member()])

    assert line == "1 row cannot be cleaned up"
