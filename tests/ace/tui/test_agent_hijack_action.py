"""Agents-tab ingress for durable Agent Hijack operations."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents import _hijack_action
from sase.ace.tui.actions.agents._hijack_action import AgentHijackActionMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_hijack_presentation import (
    apply_hijack_ledger_presentation,
)


def _agent(*, status: str = "RUNNING") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file="/tmp/project.sase",
        status=status,
        start_time=datetime(2026, 11, 3, 10, 0, 0),
        workspace_num=4,
        pid=421,
        raw_suffix="20261103100000",
        agent_name="sase-demo.1",
    )


def test_agent_can_offer_hijack_requires_flag_and_live_workspace(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(_hijack_action, "_agent_hijack_enabled", lambda: True)

    assert _hijack_action.agent_can_offer_hijack(_agent())
    assert not _hijack_action.agent_can_offer_hijack(_agent(status="DONE"))

    monkeypatch.setattr(_hijack_action, "_agent_hijack_enabled", lambda: False)
    assert not _hijack_action.agent_can_offer_hijack(_agent())


def test_hijack_submission_shows_pending_and_stop_failed_rows(
    monkeypatch: Any,
) -> None:
    agent = _agent()
    callbacks: list[Any] = []
    notifications: list[tuple[str, str]] = []

    class App(AgentHijackActionMixin):
        _agents_with_children = [agent]

        def notify(self, message: str, *, severity: str = "information") -> None:
            notifications.append((message, severity))

        def _refresh_agents_display(
            self, *, list_changed: bool, defer_detail: bool
        ) -> None:
            del list_changed, defer_detail

    app = App()
    monkeypatch.setattr(_hijack_action, "_agent_hijack_enabled", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._roster_generation.notify_roster_status_mutation",
        lambda _app: None,
    )

    def submit(_app: object, **kwargs: Any) -> bool:
        callbacks.append(kwargs["on_complete"])
        return True

    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_durable.submit_agent_hijack", submit
    )

    assert app._start_hijack_agent(agent)
    assert agent.hijack_overlay == "hijacking"

    callbacks[0](
        SimpleNamespace(
            payload={"status": "stop_failed", "severity": "error"},
            message="Surviving process 421",
            success=False,
        )
    )

    assert agent.hijack_overlay is None
    assert agent.hijack_stop_failed is True
    assert notifications == [("Surviving process 421", "error")]


def test_active_ledger_records_drive_hijack_overlays_and_summary(
    tmp_path: Any, monkeypatch: Any
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    agent = _agent()
    agent.artifacts_dir = str(artifacts_dir)
    records = [
        {
            "artifacts_dir": str(artifacts_dir),
            "state": "held",
            "repo_diffs": [
                {"files_changed": 3, "insertions": 8, "deletions": 2},
                {"files_changed": 2, "insertions": 4, "deletions": 1},
            ],
        }
    ]
    monkeypatch.setattr("sase.agent.hijack.ledger.list_active_records", lambda: records)

    apply_hijack_ledger_presentation([agent])

    assert agent.hijack_overlay is None
    assert agent.hijack_diff_summary == "5 files +12 −3"

    records[0]["state"] = "resolving"
    apply_hijack_ledger_presentation([agent])

    assert agent.hijack_overlay == "recovering"
    assert agent.hijack_diff_summary is None

    records[0]["state"] = "stopping"
    apply_hijack_ledger_presentation([agent])

    assert agent.hijack_overlay == "hijacking"


def test_remote_hijack_ingress_copies_host_command(monkeypatch: Any) -> None:
    agent = _agent()
    agent.fleet_origin_alias = "athena"
    notifications: list[str] = []
    copied: list[tuple[str, dict[str, Any]]] = []

    class App(AgentHijackActionMixin):
        def notify(self, message: str, *, severity: str = "information") -> None:
            del severity
            notifications.append(message)

    app = App()
    monkeypatch.setattr(_hijack_action, "_agent_hijack_enabled", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard.schedule_copy_delivery",
        lambda _owner, value, **kwargs: copied.append((value, kwargs)),
    )

    assert app._start_hijack_agent(agent)

    assert copied[0][0] == "sase agent hijack sase-demo.1"
    assert copied[0][1]["task_name"] == "copy-hijack-command-athena"
    assert "Agent runs on athena" in notifications[0]
