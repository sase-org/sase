"""Tests for the bare-%auto toggle (``A`` key on agents)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._approve import (
    AgentApproveMixin,
    _auto_approve_active,
)
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.proc_observer import ObservedProc as ProcInfo


def _make_agent(artifacts_dir: str, **overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
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
        # The approve handler tries selective row patching first, falling back
        # to a full refresh when the patch can't land. This fake forces the
        # fallback so the contract (in-memory mutation + refresh + persistence)
        # stays under test without a real widget tree.
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

    def _submit_durable_proc(
        self,
        argv: Any,
        *,
        operation: str = "",
        request: Any = None,
        request_fingerprint: str = "",
        concurrency_keys: Any = (),
        proc_type: str | None = None,
        display_name: str | None = None,
        cl_name: str = "",
        project_file: str = "",
        duplicate_message: str | None = None,
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
        **kwargs: Any,
    ) -> ProcInfo:
        del argv, operation, request_fingerprint, concurrency_keys
        del duplicate_message, reload_on_complete, notify_on_complete, kwargs
        proc_info = ProcInfo(
            proc_id=f"task-{len(self.scheduled)}",
            proc_type=proc_type or "agent-directive",
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message="running",
            started_at=datetime.now(),
            display_name=display_name,
        )

        async def _run() -> None:
            from sase.ops.commands.agent import _persist_directive_from_payload

            try:
                payload = dict(request or {})
                _persist_directive_from_payload(
                    payload,
                    artifacts_dir=str(payload.get("artifacts_dir") or project_file),
                )
                result = TrackedProcResult(success=True, message="ok")
            except Exception as exc:
                result = TrackedProcResult(
                    success=False,
                    message=str(exc),
                    error=str(exc),
                )
            proc_info.status = "success" if result.success else "error"
            proc_info.message = result.message
            proc_info.error = result.error
            if on_complete is not None:
                on_complete(
                    TrackedProcCompletion(
                        proc_info=proc_info,
                        success=result.success,
                        message=result.message,
                        output="",
                        payload=result.payload,
                        error=result.error,
                    )
                )

        self.scheduled.append((_run, (), {}))
        return proc_info

    def _refresh_agents_display(self, *, list_changed: bool = False) -> None:
        self.refresh_calls.append(list_changed)


# --- Pure helper ------------------------------------------------------------


def test_auto_approve_active_maps_each_state() -> None:
    assert _auto_approve_active(_make_agent("/x")) is False
    assert _auto_approve_active(_make_agent("/x", approve=True)) is True
    assert (
        _auto_approve_active(
            _make_agent("/x", approve=True, auto_approve_plan_action="tale")
        )
        is True
    )
    assert (
        _auto_approve_active(
            _make_agent("/x", approve=True, auto_approve_plan_action="epic")
        )
        is True
    )


# --- Toggle: off -> on -------------------------------------------------------


def _run_toggle_in_state(
    workdir: Any,
    *,
    record_only: bool,
    seed_meta: dict[str, Any] | None = None,
    **agent_overrides: object,
) -> dict[str, Any]:
    """Flip the ``A`` toggle once and return the persisted disk meta.

    Runs the full production path (optimistic in-memory mutation plus the
    scheduled persistence worker) with ``autonomy_record_only`` forced to
    *record_only*.
    """
    from pathlib import Path

    from sase.feature_flags import override_flags

    directory = Path(str(workdir))
    directory.mkdir(parents=True, exist_ok=True)
    if seed_meta is not None:
        (directory / "agent_meta.json").write_text(json.dumps(seed_meta))
    agent = _make_agent(str(directory), **agent_overrides)
    app = FakeApproveApp(agent)
    with override_flags(autonomy_record_only=record_only):
        app.action_toggle_auto_approve()
        asyncio.run(app.scheduled[0][0]())
    return json.loads((directory / "agent_meta.json").read_text())


def test_toggle_off_enables_bare_auto(tmp_path: Any) -> None:
    agent = _make_agent(str(tmp_path))
    app = FakeApproveApp(agent)

    app.action_toggle_auto_approve()

    assert agent.approve is True
    assert agent.auto_approve_plan_action is None
    # Optimistic refresh fired and disk write scheduled (not inline).
    assert app.refresh_calls == [True]
    assert len(app.scheduled) == 1
    assert not (tmp_path / "agent_meta.json").exists()
    assert any(msg.startswith("Auto-approve enabled") for msg, _ in app.notifications)

    asyncio.run(app.scheduled[0][0]())
    data = json.loads((tmp_path / "agent_meta.json").read_text())
    # Record-only toggle: the bare record persists, not the legacy key.
    record = data.pop("autonomy")
    assert (record["profile"], record["selection"]) == ("standard", "")
    assert data == {}

    off_data = _run_toggle_in_state(tmp_path / "off", record_only=False)
    off_record = off_data.pop("autonomy")
    assert (off_record["profile"], off_record["selection"]) == ("standard", "")
    assert off_data == {"approve": True}


def test_toggle_off_clears_stale_keys_but_preserves_others(tmp_path: Any) -> None:
    seed = {
        "auto_approve_plan_action": "tale",
        "auto_approve_argument": "tale",
        "other": "keep",
    }
    data = _run_toggle_in_state(tmp_path / "on", record_only=True, seed_meta=seed)
    record = data.pop("autonomy")
    assert (record["profile"], record["selection"]) == ("standard", "")
    assert data == {"other": "keep"}

    off_data = _run_toggle_in_state(tmp_path / "off", record_only=False, seed_meta=seed)
    off_record = off_data.pop("autonomy")
    assert (off_record["profile"], off_record["selection"]) == ("standard", "")
    assert off_data == {"other": "keep", "approve": True}


# --- Toggle: on -> off --------------------------------------------------------


def test_toggle_plain_on_disables(tmp_path: Any) -> None:
    seed = {"approve": True, "other": "keep"}
    (tmp_path / "agent_meta.json").write_text(json.dumps(seed))
    agent = _make_agent(str(tmp_path), approve=True)
    app = FakeApproveApp(agent)

    app.action_toggle_auto_approve()

    assert agent.approve is False
    assert agent.auto_approve_plan_action is None
    assert any(msg.startswith("Auto-approve disabled") for msg, _ in app.notifications)

    asyncio.run(app.scheduled[0][0]())
    data = json.loads((tmp_path / "agent_meta.json").read_text())
    # Record-only toggle-off: a manual record persists, legacy keys leave.
    record = data.pop("autonomy")
    assert (record["profile"], record["selection"]) == ("manual", "manual")
    assert data == {"other": "keep"}

    off_data = _run_toggle_in_state(
        tmp_path / "off",
        record_only=False,
        seed_meta=seed,
        approve=True,
    )
    off_record = off_data.pop("autonomy")
    assert (off_record["profile"], off_record["selection"]) == ("manual", "manual")
    assert off_data == {"other": "keep"}


def test_toggle_launch_time_epic_disables_fully(tmp_path: Any) -> None:
    seed = {
        "approve": True,
        "auto_approve_plan_action": "epic",
        "auto_approve_argument": "epic",
        "other": "keep",
    }
    data = _run_toggle_in_state(
        tmp_path / "on",
        record_only=True,
        seed_meta=seed,
        approve=True,
        auto_approve_plan_action="epic",
    )
    record = data.pop("autonomy")
    assert (record["profile"], record["selection"]) == ("manual", "manual")
    assert data == {"other": "keep"}

    off_data = _run_toggle_in_state(
        tmp_path / "off",
        record_only=False,
        seed_meta=seed,
        approve=True,
        auto_approve_plan_action="epic",
    )
    off_record = off_data.pop("autonomy")
    assert (off_record["profile"], off_record["selection"]) == ("manual", "manual")
    assert off_data == {"other": "keep"}


def test_toggle_persist_refreshes_artifact_index(tmp_path: Any) -> None:
    agent = _make_agent(str(tmp_path))
    app = FakeApproveApp(agent)

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        app.action_toggle_auto_approve()
        asyncio.run(app.scheduled[0][0]())

    update_index.assert_called_once_with(str(tmp_path))


# --- Rollback -----------------------------------------------------------------


def test_toggle_rolls_back_on_persist_failure(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A disk failure reverts the optimistic mutation and shows an error."""
    agent = _make_agent(str(tmp_path))
    app = FakeApproveApp(agent)

    def _boom(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise OSError("disk full")

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._directive_persistence.persist_agent_directive_update",
        _boom,
    )

    app.action_toggle_auto_approve()
    assert agent.approve is True  # optimistic

    asyncio.run(app.scheduled[0][0]())

    assert agent.approve is False  # rolled back
    assert agent.auto_approve_plan_action is None
    assert any(sev == "error" for _, sev in app.notifications)
    # Refresh fired twice: once optimistic, once on rollback.
    assert app.refresh_calls == [True, True]


# --- Guards -------------------------------------------------------------------


def test_toggle_no_op_off_agents_tab(tmp_path: Any) -> None:
    agent = _make_agent(str(tmp_path))
    app = FakeApproveApp(agent)
    app.current_tab = "patches"

    app.action_toggle_auto_approve()

    assert app.scheduled == []
    assert app.notifications == []
    assert agent.approve is False


def test_toggle_warns_when_status_ineligible(tmp_path: Any) -> None:
    agent = _make_agent(str(tmp_path), status="DONE")
    app = FakeApproveApp(agent)

    app.action_toggle_auto_approve()

    assert app.scheduled == []
    assert any(sev == "warning" for _, sev in app.notifications)


def test_toggle_warns_when_no_agent_selected() -> None:
    app = FakeApproveApp(None)

    app.action_toggle_auto_approve()

    assert app.scheduled == []
    assert any(sev == "warning" for _, sev in app.notifications)


def test_toggle_warns_when_no_artifacts_dir() -> None:
    agent = _make_agent("")
    app = FakeApproveApp(agent)
    with patch.object(Agent, "get_artifacts_dir", return_value=None):
        app._set_auto_approve(agent, enabled=True)

    assert app.scheduled == []
    assert any(sev == "warning" for _, sev in app.notifications)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
