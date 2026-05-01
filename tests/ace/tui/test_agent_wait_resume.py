"""Tests for Agents-tab wait/resume actions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sase.ace.tui.actions.agents._wait_resume import (
    AgentWaitResumeMixin,
    _parse_wait_dependency_names,
)
from sase.ace.tui.models.agent import Agent, AgentType


def _make_waiting_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.gp",
        "status": "WAITING",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": "20240101120000",
        "waiting_for": ["old_dep"],
        "wait_duration": 300.0,
        "wait_until": "2026-05-01T12:00:00",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class _FakeWaitResumeApp(AgentWaitResumeMixin):
    """Minimal app implementing what _apply_wait touches."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.refresh_calls = 0

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        del list_changed, defer_detail
        self.refresh_calls += 1


def test_parse_wait_dependency_names_splits_commas() -> None:
    assert _parse_wait_dependency_names("alice, bob,, ") == ["alice", "bob"]


def test_apply_wait_overwrites_wait_conditions(tmp_path: Path) -> None:
    waiting_path = tmp_path / "waiting.json"
    waiting_path.write_text(
        json.dumps(
            {
                "waiting_for": ["old_dep"],
                "wait_duration": 300.0,
                "wait_until": "2026-05-01T12:00:00",
                "cl_name": "test_cl",
                "timestamp": "20240101120000",
            }
        ),
        encoding="utf-8",
    )
    agent = _make_waiting_agent()
    app = _FakeWaitResumeApp()

    app._apply_wait(str(tmp_path), agent, "alice, bob,, ")

    data = json.loads(waiting_path.read_text(encoding="utf-8"))
    assert data == {
        "cl_name": "test_cl",
        "timestamp": "20240101120000",
        "waiting_for": ["alice", "bob"],
    }
    assert agent.waiting_for == ["alice", "bob"]
    assert agent.wait_duration is None
    assert agent.wait_until is None
    assert app.notifications == [("Now waiting for: alice, bob", "information")]
    assert app.refresh_calls == 1


def test_apply_wait_empty_submission_keeps_run_now_behavior(tmp_path: Path) -> None:
    agent = _make_waiting_agent(waiting_for=["old_dep"], wait_duration=None)
    app = _FakeWaitResumeApp()

    app._apply_wait(str(tmp_path), agent, "")

    ready_path = tmp_path / "ready.json"
    assert json.loads(ready_path.read_text(encoding="utf-8")) == {
        "resolved_deps": ["old_dep"],
        "unwait": True,
    }
    assert agent.waiting_for == ["old_dep"]
    assert app.notifications == [("Wait: test_cl", "information")]
