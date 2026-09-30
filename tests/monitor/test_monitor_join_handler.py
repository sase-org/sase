"""Join request validation and join-start display for ``monitor start -J``."""

from __future__ import annotations

import json
from typing import Any

import pytest

from sase.core.tool_run import tool_run_join, tool_run_request_stop
from sase.monitor.models import MonitorRecord
from sase.monitor.request import StartMonitorRequest
from tests.main.monitor_handler_helpers import dispatch, pin_project

from ._join_helpers import (
    join_env as join_env,
    reserve_detached_run,
    settle_detached_run,
)

__all__ = [
    "test_join_joined_elsewhere_is_refused",
    "test_join_label_reason_and_command_derive_from_the_run",
    "test_join_non_detached_run_is_refused",
    "test_join_other_agents_run_is_refused",
    "test_join_rejects_a_command_remainder",
    "test_join_rejects_an_explicit_agent",
    "test_join_rejects_completion_and_points_at_next",
    "test_join_rejects_hidden_command_alias",
    "test_join_requires_an_agent",
    "test_join_settled_run_is_refused_with_state_and_pointer",
    "test_join_start_builds_a_join_request_and_reports_joined",
    "test_join_start_json_reports_tool_run_joined",
    "test_join_stop_requested_run_is_refused",
    "test_join_unknown_run_is_refused",
]


def _agent(monkeypatch: pytest.MonkeyPatch, name: str = "agent-1") -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", name)


# Handler validation: usage refusals exit 2.
def test_join_requires_an_agent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert dispatch(["monitor", "start", "-J", "abc123", "-p", "verify"]) == 2
    assert "only available inside an agent" in capsys.readouterr().err


def test_join_rejects_a_command_remainder(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _agent(monkeypatch)
    code = dispatch(
        ["monitor", "start", "-J", "abc123", "-p", "verify", "--", "just", "check"]
    )
    assert code == 2
    assert "command remainder" in capsys.readouterr().err


def test_join_rejects_hidden_command_alias(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _agent(monkeypatch)
    code = dispatch(["monitor", "start", "-J", "abc123", "-p", "verify", "-c", "true"])
    assert code == 2
    assert "-c/--command" in capsys.readouterr().err


def test_join_rejects_completion_and_points_at_next(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _agent(monkeypatch)
    code = dispatch(["monitor", "start", "-J", "abc123", "-p", "verify", "-f", "ref-1"])
    assert code == 2
    err = capsys.readouterr().err
    assert "-f/--completion" in err
    assert "-n/--next" in err


def test_join_rejects_an_explicit_agent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _agent(monkeypatch)
    code = dispatch(["monitor", "start", "-J", "abc123", "-p", "verify", "-a", "other"])
    assert code == 2
    assert "-a/--agent" in capsys.readouterr().err


def test_join_unknown_run_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _agent(monkeypatch)
    reserve_detached_run("--", "true")
    code = dispatch(["monitor", "start", "-J", "deadbeef" * 4, "-p", "verify"])
    assert code == 2
    assert "was not found" in capsys.readouterr().err


def test_join_non_detached_run_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.tool.argv import resolve_run_argv
    from sase.tool.handoff import reserve_handoff_run

    _agent(monkeypatch)
    resolved = resolve_run_argv(["--", "true"])
    reservation = reserve_handoff_run(
        resolved, owner_kind="proc", owner_id="proc-plain", agent="agent-1"
    )
    assert reservation.reserved
    code = dispatch(["monitor", "start", "-J", reservation.run_id, "-p", "verify"])
    assert code == 2
    assert "not a detached run" in capsys.readouterr().err


def test_join_other_agents_run_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _agent(monkeypatch, "agent-1")
    run_id = reserve_detached_run("--", "true", agent="agent-2")
    code = dispatch(["monitor", "start", "-J", run_id, "-p", "verify"])
    assert code == 2
    assert "belongs to agent" in capsys.readouterr().err


# Handler validation: state races exit 1 with a show pointer.
def test_join_settled_run_is_refused_with_state_and_pointer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _agent(monkeypatch)
    run_id = reserve_detached_run("--", "true")
    settle_detached_run(run_id, state="succeeded", exit_code=0, terminal_cause="exited")
    code = dispatch(["monitor", "start", "-J", run_id, "-p", "verify"])
    assert code == 1
    err = capsys.readouterr().err
    assert "already succeeded" in err
    assert f"sase tool show {run_id}" in err


def test_join_stop_requested_run_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _agent(monkeypatch)
    run_id = reserve_detached_run("--", "sleep", "30")
    tool_run_request_stop(
        {
            "schema_version": 1,
            "run_id": run_id,
            "requested_by": "agent-1",
            "reason": "stop",
        }
    )
    code = dispatch(["monitor", "start", "-J", run_id, "-p", "verify"])
    assert code == 1
    err = capsys.readouterr().err
    assert "stop request" in err
    assert f"sase tool show {run_id}" in err


def test_join_joined_elsewhere_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _agent(monkeypatch)
    run_id = reserve_detached_run("--", "sleep", "30")
    joined = tool_run_join(
        {
            "schema_version": 1,
            "run_id": run_id,
            "joiner_kind": "monitor",
            "joiner_id": "mon-elsewhere",
            "agent": "agent-1",
        }
    )
    assert joined.get("outcome") == "joined"
    code = dispatch(["monitor", "start", "-J", run_id, "-p", "verify"])
    assert code == 1
    err = capsys.readouterr().err
    assert "already joined" in err
    assert "mon-elsewhere" in err
    assert f"sase tool show {run_id}" in err


# Join display values derive from the original ToolRun.
def test_join_label_reason_and_command_derive_from_the_run() -> None:
    from sase.monitor.join import (
        _canonical_join_words,
        _join_display_command,
        _join_tool_name,
        default_join_label,
        default_join_reason,
    )

    named = {"tool_name": "check", "display_argv": ["check"]}
    assert _join_tool_name(named) == "check"
    assert default_join_label(named) == "tool:check (joined)"
    assert default_join_reason(named) == "finish check (joined run)"
    assert _join_display_command(named) == "sase tool run check"
    assert _canonical_join_words(named) == ["check"]

    adhoc = {"display_argv": ["echo", "hi"]}
    assert _join_tool_name(adhoc) == "ad-hoc"
    assert default_join_label(adhoc) == "tool:ad-hoc (joined)"
    assert default_join_reason(adhoc) == "finish ad-hoc (joined run)"
    assert _join_display_command(adhoc) == "sase tool run -- echo hi"


def _fake_record(**overrides: object) -> MonitorRecord:
    fields: dict[str, Any] = {
        "monitor_id": "mon-joined-1",
        "member_agent_name": "agent-1--mon",
        "lane": "agent-1",
        "project_name": "proj",
        "artifacts_dir": "/tmp/artifacts",
        "timestamp": "20260930120000",
        "command": "sase tool run -- true",
        "cwd": "/tmp",
        "reason": "finish ad-hoc (joined run)",
        "label": "tool:ad-hoc (joined)",
        "start_status": "TESTING",
        "stop_status": "TESTED",
        "timeout_seconds": 30.0,
        "tail_lines": 200,
        "monitor_state": "running",
        "tool_run_id": "run-1",
        "tool_run_joined": True,
    }
    fields.update(overrides)
    return MonitorRecord(**fields)  # type: ignore[arg-type]


def test_join_start_builds_a_join_request_and_reports_joined(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sase.main.monitor.start as handler

    _agent(monkeypatch)
    pin_project(monkeypatch)
    run_id = reserve_detached_run("--", "true")
    captured: dict[str, Any] = {}

    def _fake_start(request: StartMonitorRequest) -> MonitorRecord:
        captured["request"] = request
        return _fake_record(tool_run_id=request.join_run_id)

    monkeypatch.setattr(handler, "start_monitor", _fake_start)
    monkeypatch.setattr(handler, "will_handoff_monitor_to_agent_runner", lambda: False)
    monkeypatch.setattr(
        handler, "maybe_handoff_monitor_from_agent", lambda _record: False
    )
    code = dispatch(["monitor", "start", "-J", run_id, "-p", "verify"])
    assert code == 0
    request = captured["request"]
    assert request.join_run_id == run_id
    assert request.command == "sase tool run -- true"
    assert request.label == "tool:ad-hoc (joined)"
    assert request.reason == "finish ad-hoc (joined run)"
    out = capsys.readouterr().out
    assert f"tool run: {run_id} (joined)" in out


def test_join_start_json_reports_tool_run_joined(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import sase.main.monitor.start as handler

    _agent(monkeypatch)
    pin_project(monkeypatch)
    run_id = reserve_detached_run("--", "true")
    monkeypatch.setattr(handler, "start_monitor", lambda request: _fake_record())
    monkeypatch.setattr(handler, "will_handoff_monitor_to_agent_runner", lambda: False)
    monkeypatch.setattr(
        handler, "maybe_handoff_monitor_from_agent", lambda _record: False
    )
    code = dispatch(["monitor", "start", "-J", run_id, "-p", "verify", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["monitor"]["tool_run_joined"] is True
