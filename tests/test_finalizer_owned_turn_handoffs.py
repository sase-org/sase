"""Finalizer-owned turns refuse turn-ending handoffs (sase-1h9.3)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agent.handoff_inflight import HANDOFF_INFLIGHT_MARKER
from sase.agent.pending_handoff import PIPE_PENDING_MARKER
from sase.agent.pending_handoff_write import (
    PendingHandoffError,
    handoff_guard,
    write_pending_handoff_marker,
)
from sase.axe.run_agent_exec_finalize import _finalizer_reports_failure
from sase.finalizers.controller_run import _controller_failure_for_handoff
from sase.finalizers.owned_turn import (
    SASE_FINALIZER_OWNED_TURN_ENV,
    finalizer_owned_turn,
    finalizer_owned_turn_is_active,
    finalizer_owned_turn_refusal,
)
from sase.monitor import MonitorError
from sase.monitor.start_flow import (
    _finalizer_owned_monitor_refusal,
    refuse_finalizer_owned_monitor_start,
)
from sase.tool.routing import escalation_block, escalation_json, is_joinable


def _joinable_run() -> dict:
    return {
        "state": "running",
        "starter": {"agent": "agent-1"},
        "run_id": "abc",
        "tool_name": "check",
    }


def _budget() -> dict:
    return {"budget_seconds": 510, "source": "hard", "ceiling_seconds": 600}


def test_owned_turn_active_truthy_parsing() -> None:
    for raw in ("1", "true", "yes", "on", " TRUE ", "On"):
        assert (
            finalizer_owned_turn_is_active({SASE_FINALIZER_OWNED_TURN_ENV: raw}) is True
        )
    for raw in ("", "0", "false", "no", "off"):
        assert (
            finalizer_owned_turn_is_active({SASE_FINALIZER_OWNED_TURN_ENV: raw})
            is False
        )
    assert finalizer_owned_turn_is_active({}) is False


def test_owned_turn_context_manager_marks_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    monkeypatch.delenv(SASE_FINALIZER_OWNED_TURN_ENV, raising=False)
    assert finalizer_owned_turn_is_active() is False
    with finalizer_owned_turn():
        assert finalizer_owned_turn_is_active() is True
        assert os.environ.get(SASE_FINALIZER_OWNED_TURN_ENV) == "1"
    assert finalizer_owned_turn_is_active() is False


def test_refusal_names_command_and_repair() -> None:
    message = finalizer_owned_turn_refusal("sase pipe")
    assert "sase pipe" in message
    assert "cannot end the agent run" in message
    assert "in this turn" in message
    hinted = finalizer_owned_turn_refusal("sase monitor start", inline_hint="hint")
    assert hinted.endswith("hint")


def test_refuse_finalizer_owned_monitor_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SASE_FINALIZER_OWNED_TURN_ENV, raising=False)
    assert refuse_finalizer_owned_monitor_start() is None
    monkeypatch.setenv(SASE_FINALIZER_OWNED_TURN_ENV, "1")
    with pytest.raises(MonitorError, match="sase monitor start"):
        refuse_finalizer_owned_monitor_start()
    assert "sase tool wait" in _finalizer_owned_monitor_refusal()


def test_start_monitor_refuses_before_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.monitor import request as request_module
    from sase.monitor import start_flow as start_flow_module

    monkeypatch.setenv(SASE_FINALIZER_OWNED_TURN_ENV, "1")
    monkeypatch.setattr(
        start_flow_module,
        "resolve_start_identity",
        lambda request: pytest.fail("identity resolution must not run"),
    )
    monkeypatch.setattr(
        start_flow_module,
        "create_monitor_member",
        lambda *args, **kwargs: pytest.fail("member creation must not run"),
    )
    request = request_module.StartMonitorRequest(
        command="true",
        reason="verify",
        timeout_seconds=30.0,
        cwd="/tmp",
        project_name="proj",
        start_status="TESTING",
        stop_status="TESTED",
    )
    with pytest.raises(MonitorError, match="host finalizer turn"):
        start_flow_module.start_monitor(request)


def test_handle_monitor_start_refuses_finalizer_owned_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    from sase.main.monitor import start as start_handler

    monkeypatch.setenv(SASE_FINALIZER_OWNED_TURN_ENV, "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    calls: list = []
    monkeypatch.setattr(
        start_handler, "start_monitor", lambda request: calls.append(request)
    )
    assert start_handler.handle_monitor_start(SimpleNamespace()) == 1
    assert calls == []
    assert "sase monitor start" in capsys.readouterr().err
    assert not (tmp_path / HANDOFF_INFLIGHT_MARKER).exists()


def test_handoff_guard_refuses_finalizer_owned_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    assert handoff_guard(command="sase pipe") == str(tmp_path)
    monkeypatch.setenv(SASE_FINALIZER_OWNED_TURN_ENV, "1")
    with pytest.raises(PendingHandoffError, match="sase pipe.*host finalizer turn"):
        handoff_guard(command="sase pipe")


def test_write_pending_handoff_marker_refuses_finalizer_owned_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(SASE_FINALIZER_OWNED_TURN_ENV, "1")
    with pytest.raises(PendingHandoffError, match="host finalizer turn"):
        write_pending_handoff_marker(
            PIPE_PENDING_MARKER, {"prompt": "x"}, artifacts_dir=str(tmp_path)
        )
    assert not (tmp_path / PIPE_PENDING_MARKER).exists()


def test_is_joinable_refuses_finalizer_owned_turn() -> None:
    run = _joinable_run()
    assert is_joinable(run, env={"SASE_AGENT_NAME": "agent-1"}) is True
    assert (
        is_joinable(
            run,
            env={"SASE_AGENT_NAME": "agent-1", SASE_FINALIZER_OWNED_TURN_ENV: "1"},
        )
        is False
    )


def test_escalation_block_omits_join_in_finalizer_turn() -> None:
    env = {"SASE_AGENT_NAME": "agent-1", SASE_FINALIZER_OWNED_TURN_ENV: "1"}
    block = escalation_block(_joinable_run(), _budget(), "abc", env=env)
    assert "monitor start -J" not in block
    assert "sase tool wait abc" in block
    plain = escalation_block(
        _joinable_run(), _budget(), "abc", env={"SASE_AGENT_NAME": "agent-1"}
    )
    assert "monitor start -J abc" in plain


def test_escalation_json_not_joinable_has_no_join_command() -> None:
    payload = escalation_json("abc", _budget(), False, "check")
    assert payload["joinable"] is False
    assert payload["join_command"] is None


def test_controller_failure_for_handoff(tmp_path: Path) -> None:
    exc = RuntimeError("provider exited 143")
    assert _controller_failure_for_handoff(exc, None) is None
    assert _controller_failure_for_handoff(exc, str(tmp_path)) is None
    (tmp_path / ".sase_monitor_pending").write_text(
        json.dumps({"monitor_id": "m"}), encoding="utf-8"
    )
    failure = _controller_failure_for_handoff(exc, str(tmp_path))
    assert failure is not None
    code, message = failure
    assert code == "finalizer_turn_handoff"
    assert "monitor" in message
    assert "143" in message


def test_finalizer_reports_failure(tmp_path: Path) -> None:
    assert _finalizer_reports_failure(None) is False
    assert _finalizer_reports_failure(str(tmp_path)) is False
    result = tmp_path / "finalizer_result.json"
    result.write_text(json.dumps({"status": "success"}), encoding="utf-8")
    assert _finalizer_reports_failure(str(tmp_path)) is False
    result.write_text(json.dumps({"status": "failed"}), encoding="utf-8")
    assert _finalizer_reports_failure(str(tmp_path)) is True
    result.write_text("{not json", encoding="utf-8")
    assert _finalizer_reports_failure(str(tmp_path)) is False
