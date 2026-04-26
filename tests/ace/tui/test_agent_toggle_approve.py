"""Tests for the optimistic + async ``action_toggle_approve`` flow."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import pytest

from sase.ace.tui.actions.agents._approve import (
    AgentApproveMixin,
    persist_approve_field,
)
from sase.ace.tui.models.agent import Agent, AgentType


def _make_agent(artifacts_dir: str, **overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.gp",
        "status": "RUNNING",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": "20240101120000",
        "artifacts_dir": artifacts_dir,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class FakeApproveApp(AgentApproveMixin):
    def __init__(self, agent: Agent | None) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = [agent] if agent is not None else []
        self._selected = agent
        self.notifications: list[tuple[str, str]] = []
        self.scheduled: list[tuple[Any, tuple[Any, ...], dict[str, Any]]] = []
        self.refresh_calls: list[bool] = []
        # Phase 3 (sase-u.3): the approve handler tries selective row
        # patching first, falling back to a full refresh when the patch
        # can't land. This fake forces the fallback so the existing
        # contract (in-memory mutation + refresh + persistence) stays
        # under test without a real widget tree.
        self.patch_attempts: int = 0

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        del agent
        self.patch_attempts += 1
        return False

    def _get_selected_agent(self) -> Agent | None:
        return self._selected

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def call_later(self, callback: Any, *args: Any, **kwargs: Any) -> None:
        self.scheduled.append((callback, args, kwargs))

    def _refresh_agents_display(self, *, list_changed: bool = False) -> None:
        self.refresh_calls.append(list_changed)


def testpersist_approve_field_writes_new_file(tmp_path: Any) -> None:
    meta_path = tmp_path / "agent_meta.json"
    persist_approve_field(meta_path, True)
    assert json.loads(meta_path.read_text()) == {"approve": True}


def testpersist_approve_field_preserves_other_keys(tmp_path: Any) -> None:
    meta_path = tmp_path / "agent_meta.json"
    meta_path.write_text(json.dumps({"approve": False, "other": "keep"}))
    persist_approve_field(meta_path, True)
    data = json.loads(meta_path.read_text())
    assert data["approve"] is True
    assert data["other"] == "keep"


def test_action_toggle_approve_optimistic_update(tmp_path: Any) -> None:
    """The in-memory toggle and refresh happen before any disk write."""
    agent = _make_agent(str(tmp_path))
    assert agent.approve is False
    app = FakeApproveApp(agent)

    app.action_toggle_approve()

    # Optimistic mutation already applied
    assert agent.approve is True
    # Display refreshed inline so the keystroke feels instant
    assert app.refresh_calls == [True]
    # User saw confirmation toast
    assert any(msg.startswith("Auto-approve enabled") for msg, _ in app.notifications)
    # Disk write was scheduled, not performed inline
    assert len(app.scheduled) == 1
    # File hasn't been written yet on the UI thread
    assert not (tmp_path / "agent_meta.json").exists()


def test_action_toggle_approve_persists_via_worker(tmp_path: Any) -> None:
    """Running the scheduled coroutine writes the file in the worker."""
    agent = _make_agent(str(tmp_path))
    app = FakeApproveApp(agent)
    app.action_toggle_approve()
    callback = app.scheduled[0][0]

    asyncio.run(callback())

    data = json.loads((tmp_path / "agent_meta.json").read_text())
    assert data == {"approve": True}
    # No error toast
    assert not any(sev == "error" for _, sev in app.notifications)


def test_action_toggle_approve_rolls_back_on_persist_failure(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disk failure reverts the optimistic mutation and shows an error toast."""
    agent = _make_agent(str(tmp_path))
    app = FakeApproveApp(agent)

    def _boom(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise OSError("disk full")

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._approve.persist_approve_field", _boom
    )
    app.action_toggle_approve()
    assert agent.approve is True  # optimistic

    callback = app.scheduled[0][0]
    asyncio.run(callback())

    assert agent.approve is False  # rolled back
    assert any(sev == "error" for _, sev in app.notifications)
    # Refresh fired twice: once optimistic, once on rollback
    assert app.refresh_calls == [True, True]


def test_action_toggle_approve_warns_when_status_ineligible(tmp_path: Any) -> None:
    agent = _make_agent(str(tmp_path), status="DONE")
    app = FakeApproveApp(agent)

    app.action_toggle_approve()

    assert agent.approve is False
    assert app.scheduled == []
    assert any(sev == "warning" for _, sev in app.notifications)


def test_action_toggle_approve_no_op_off_agents_tab(tmp_path: Any) -> None:
    agent = _make_agent(str(tmp_path))
    app = FakeApproveApp(agent)
    app.current_tab = "changespecs"

    app.action_toggle_approve()

    assert agent.approve is False
    assert app.scheduled == []
    assert app.notifications == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
