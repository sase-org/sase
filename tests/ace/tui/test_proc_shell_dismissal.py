"""Dismiss finished stand-alone proc-shell rows from the Agents tab."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents import AgentsMixin
from sase.ace.tui.actions.agents._dismissing import AgentDismissingMixin
from sase.ace.tui.actions.agents._marking_kill import AgentMarkedKillMixin
from sase.ace.tui.actions.agents._proc_shell_dismiss import ProcShellDismissMixin
from sase.ace.tui.models.agent import Agent, AgentType


_NOW = datetime(2026, 8, 23, 12, 0, 0)


class _KillDispatchApp(AgentsMixin):
    def __init__(self, agent: Agent) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = [agent]
        self._agents_with_children = [agent]
        self._marked_agents = set()
        self._current_group_key = None
        self._dismissed_proc_shells: set[str] = set()
        self._notifications: list[tuple[str, str]] = []
        self.pushed: list[tuple[object, Callable[[bool], None]]] = []
        self.dismissed_rows: list[list[Agent]] = []

    def notify(self, msg: str, severity: str = "information") -> None:
        self._notifications.append((msg, severity))

    def push_screen(self, modal: object, callback: Callable[[bool], None]) -> None:
        self.pushed.append((modal, callback))

    def _get_selected_agent(self) -> Agent | None:
        return self._agents[self.current_idx] if self._agents else None

    def _dismiss_proc_shell_rows(self, agents: list[Agent]) -> None:
        self.dismissed_rows.append(list(agents))


class _BulkDismissApp(
    ProcShellDismissMixin, AgentDismissingMixin, AgentMarkedKillMixin
):
    def __init__(self, agents: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self._marked_agent_order: list[tuple[AgentType, str, str | None]] = []
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._dismissed_proc_shells: set[str] = set()
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}
        self._dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]] = (
            set()
        )
        self._notifications: list[tuple[str, str]] = []
        self.pushed: list[object] = []
        self.dismissed_agents: list[list[Agent]] = []
        self.bulk_killed: list[tuple[list[Agent], list[Agent]]] = []

    def notify(self, msg: str, severity: str = "information") -> None:
        self._notifications.append((msg, severity))

    def push_screen(self, modal: object, callback: Callable[[Any], None]) -> None:
        self.pushed.append(modal)
        callback(True)

    def _do_dismiss_all(self, agents: list[Agent]) -> None:
        self.dismissed_agents.append(list(agents))
        self._dismissed_agent_objects.extend(agents)

    def _do_bulk_kill_agents(
        self,
        killable: list[Agent],
        dismissable: list[Agent] | None = None,
    ) -> None:
        dismissable = dismissable or []
        self.bulk_killed.append((list(killable), list(dismissable)))
        self._dismissed_agent_objects.extend(dismissable)

    def _refilter_agents(self, *, prior_pos: int | None = None, **_kwargs: Any) -> None:
        del prior_pos
        self._agents = list(self._agents_with_children)

    def _capture_focused_visible_pos(self) -> int | None:
        return None


def _proc_shell(
    *,
    proc_id: str = "abc123def456",
    status: str = "DONE",
    proc_status: str = "success",
    label: str = "unit-1",
) -> Agent:
    return Agent(
        agent_type=AgentType.PROC_SHELL,
        cl_name="sase",
        project_file="",
        status=status,
        start_time=_NOW,
        raw_suffix=proc_id,
        proc_id=proc_id,
        proc_status=proc_status,
        proc_label=label,
        agent_name=label,
    )


def _done_agent(cl_name: str = "feature") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=_NOW,
        raw_suffix="20260823120000",
        agent_name=cl_name,
    )


def _gate_agent(
    *,
    cl_name: str = "gate",
    gate_state: str = "pending",
    raw_suffix: str = "20260823130000",
) -> Agent:
    status = "GATED" if gate_state == "pending" else "GATE DONE"
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=_NOW,
        raw_suffix=raw_suffix,
        agent_name=cl_name,
    )
    agent.agent_family_role = "gate"
    agent.role_suffix = "--gate"
    agent.gate_id = f"{cl_name}-gate"
    agent.gate_kind = "approval"
    agent.gate_state = gate_state
    assert agent.is_gate is True
    return agent


def test_action_kill_agent_dismisses_terminal_proc_shell() -> None:
    agent = _proc_shell()
    app = _KillDispatchApp(agent)

    app.action_kill_agent()

    assert app.dismissed_rows == [[agent]]
    assert app.pushed == []
    assert ("Proc shell has already finished", "warning") not in app._notifications


def test_action_kill_agent_on_running_proc_shell_confirms_kill() -> None:
    agent = _proc_shell(status="RUNNING", proc_status="running")
    app = _KillDispatchApp(agent)

    app.action_kill_agent()

    assert app.dismissed_rows == []
    assert len(app.pushed) == 1
    assert app.pushed[0][0].__class__.__name__ == "ConfirmKillProcShellModal"
    assert ("Proc shell has already finished", "warning") not in app._notifications


def test_dismiss_all_done_dismisses_agent_and_terminal_proc_shell() -> None:
    done = _done_agent()
    proc = _proc_shell()
    app = _BulkDismissApp([done, proc])

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_bundle") as save_bundle,
        patch(
            "sase.ace.tui.actions.agents._killing_utils.delete_agent_artifacts"
        ) as delete_artifacts,
    ):
        app._dismiss_all_done_agents_global()

    assert app.dismissed_agents == [[done]]
    assert proc.proc_id in app._dismissed_proc_shells
    assert all(agent.identity != proc.identity for agent in app._agents)
    assert all(agent.identity != proc.identity for agent in app._agents_with_children)
    assert [agent.identity for agent in app._dismissed_agent_objects] == [done.identity]
    save_bundle.assert_not_called()
    delete_artifacts.assert_not_called()


def test_marked_bulk_kill_dismisses_terminal_proc_shell() -> None:
    done = _done_agent()
    proc = _proc_shell()
    app = _BulkDismissApp([done, proc])

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_bundle") as save_bundle,
        patch(
            "sase.ace.tui.actions.agents._killing_utils.delete_agent_artifacts"
        ) as delete_artifacts,
    ):
        app._present_bulk_kill_modal([done, proc])

    assert app.bulk_killed == [([], [done])]
    assert proc.proc_id in app._dismissed_proc_shells
    assert [agent.identity for agent in app._dismissed_agent_objects] == [done.identity]
    description = app.pushed[0].agent_description
    assert "Dismiss 1 proc shell" in description
    save_bundle.assert_not_called()
    delete_artifacts.assert_not_called()


def test_marked_bulk_kill_skips_pending_gate() -> None:
    pending_gate = _gate_agent(gate_state="pending")
    app = _BulkDismissApp([pending_gate])

    app._present_bulk_kill_modal([pending_gate])

    assert app.bulk_killed == []
    assert app.pushed == []
    assert app._notifications == [("Skipping 1 gate waiting for a decision", "warning")]


def test_marked_bulk_kill_dismisses_terminal_gate() -> None:
    terminal_gate = _gate_agent(gate_state="answered")
    app = _BulkDismissApp([terminal_gate])

    app._present_bulk_kill_modal([terminal_gate])

    assert app.bulk_killed == [([], [terminal_gate])]
    assert [agent.identity for agent in app._dismissed_agent_objects] == [
        terminal_gate.identity
    ]


def test_marked_bulk_kill_mixed_batch_skips_pending_gate() -> None:
    done = _done_agent()
    pending_gate = _gate_agent(gate_state="pending")
    app = _BulkDismissApp([done, pending_gate])

    app._present_bulk_kill_modal([done, pending_gate])

    assert app.bulk_killed == [([], [done])]
    assert [agent.identity for agent in app._dismissed_agent_objects] == [done.identity]
    assert "Skipping 1 gate waiting for a decision" in app.pushed[0].agent_description


def test_marked_bulk_kill_skips_active_proc_shell() -> None:
    running = _proc_shell(status="RUNNING", proc_status="running")
    app = _BulkDismissApp([running])

    app._present_bulk_kill_modal([running])

    assert app.bulk_killed == []
    assert app._dismissed_proc_shells == set()
    assert running in app._agents
    assert app.pushed == []
    assert app._notifications == [("Skipping 1 running proc shell", "warning")]
