"""Monitor joins: ``sase monitor start -J/--join RUN`` and the join worker lane."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.config.core import clear_config_cache
from sase.core.tool_run import (
    tool_run_claim,
    tool_run_join,
    tool_run_request_stop,
    tool_run_show,
)
from sase.monitor.models import MonitorRecord
from sase.monitor.request import StartMonitorRequest
from sase.running_field import WorkspaceClaim
from sase.tool.argv import resolve_run_argv
from sase.tool.executor_recording import finish_tool_run
from sase.tool.handoff import reserve_handoff_run
from tests.main.monitor_handler_helpers import dispatch, monitor_home, pin_project
from tests.monitor._fixtures import (
    make_starter_agent,
    patch_project_records,
    write_project_file,
)

__all__ = ["monitor_home"]


@pytest.fixture(autouse=True)
def _join_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_ARTIFACTS_DIR",
        "SASE_MONITOR_ID",
        "SASE_PROC_ID",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_EVENTS",
    ):
        monkeypatch.delenv(key, raising=False)
    clear_config_cache()


def _agent(monkeypatch: pytest.MonkeyPatch, name: str = "agent-1") -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", name)


def _starter(agent: str = "agent-1") -> dict[str, object]:
    return {
        "agent": agent,
        "pid": os.getpid(),
        "boot_id": "boot-1",
        "process_start_identity": "boot-1:1",
    }


def _reserve_detached(
    *words: str, agent: str = "agent-1", owner_id: str = "proc-join-engine"
) -> str:
    resolved = resolve_run_argv(list(words))
    reservation = reserve_handoff_run(
        resolved,
        owner_kind="proc",
        owner_id=owner_id,
        agent=agent,
        starter=_starter(agent),
    )
    assert reservation.reserved, reservation.error
    return reservation.run_id


def _settle(
    run_id: str,
    *,
    state: str,
    exit_code: int | None,
    terminal_cause: str,
    owner_id: str = "proc-join-engine",
) -> None:
    claimed = tool_run_claim(
        {
            "schema_version": 1,
            "run_id": run_id,
            "owner_kind": "proc",
            "owner_id": owner_id,
            "wrapper_pid": os.getpid(),
            "boot_id": "boot-1",
            "process_start_identity": "boot-1:1",
        }
    )
    assert claimed.get("outcome") == "claimed", claimed
    assert finish_tool_run(
        run_id,
        state=state,
        exit_code=exit_code,
        duration_ms=9,
        terminal_cause=terminal_cause,
    )


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
    _reserve_detached("--", "true")
    code = dispatch(["monitor", "start", "-J", "deadbeef" * 4, "-p", "verify"])
    assert code == 2
    assert "was not found" in capsys.readouterr().err


def test_join_non_detached_run_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
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
    run_id = _reserve_detached("--", "true", agent="agent-2")
    code = dispatch(["monitor", "start", "-J", run_id, "-p", "verify"])
    assert code == 2
    assert "belongs to agent" in capsys.readouterr().err


# Handler validation: state races exit 1 with a show pointer.
def test_join_settled_run_is_refused_with_state_and_pointer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _agent(monkeypatch)
    run_id = _reserve_detached("--", "true")
    _settle(run_id, state="succeeded", exit_code=0, terminal_cause="exited")
    code = dispatch(["monitor", "start", "-J", run_id, "-p", "verify"])
    assert code == 1
    err = capsys.readouterr().err
    assert "already succeeded" in err
    assert f"sase tool show {run_id}" in err


def test_join_stop_requested_run_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _agent(monkeypatch)
    run_id = _reserve_detached("--", "sleep", "30")
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
    run_id = _reserve_detached("--", "sleep", "30")
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
    run_id = _reserve_detached("--", "true")
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
    run_id = _reserve_detached("--", "true")
    monkeypatch.setattr(handler, "start_monitor", lambda request: _fake_record())
    monkeypatch.setattr(handler, "will_handoff_monitor_to_agent_runner", lambda: False)
    monkeypatch.setattr(
        handler, "maybe_handoff_monitor_from_agent", lambda _record: False
    )
    code = dispatch(["monitor", "start", "-J", run_id, "-p", "verify", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["monitor"]["tool_run_joined"] is True


# Engine: the start transaction records the join before the proc submits.
_FAKE_SUPERVISOR_PID = 2**28 + 13


def _lane(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    write_project_file(
        "proj",
        running_claims=[WorkspaceClaim(3, "ace-run", "acme", pid=os.getpid())],
    )
    starter_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme",
        model="claude-sonnet-5",
        workspace_dir=str(tmp_path),
        workspace_num=3,
        pid=os.getpid(),
        cl_name="acme",
    )
    patch_project_records(monkeypatch, [starter_dir])
    return starter_dir


def _join_request(
    run_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> StartMonitorRequest:
    from sase.monitor.join import (
        default_join_label,
        default_join_reason,
        inspect_join_target,
    )

    target = inspect_join_target(run_id, "acme")
    assert not hasattr(target, "exit_code"), target
    return StartMonitorRequest(
        command=target.command,  # type: ignore[union-attr]
        reason=default_join_reason(target.run),  # type: ignore[union-attr]
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        start_status="TESTING",
        stop_status="TESTED",
        label=default_join_label(target.run),  # type: ignore[union-attr]
        join_run_id=run_id,
    )


def _fake_submit_factory(captured: list[Any]):  # type: ignore[no-untyped-def]
    def _fake_submit(request: Any, *, after_spawn: Any, after_ack: Any) -> Any:
        captured.append(request)
        after_spawn(SimpleNamespace(pid=_FAKE_SUPERVISOR_PID))
        after_ack(SimpleNamespace(pid=_FAKE_SUPERVISOR_PID, supervisor_id="sup-fake"))
        return SimpleNamespace(pid=_FAKE_SUPERVISOR_PID, supervisor_id="sup-fake")

    return _fake_submit


def _mock_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.monitor.start_launch.claim_monitor_workspace",
        lambda *args, **kwargs: SimpleNamespace(
            result=SimpleNamespace(success=True), starter_claim=None
        ),
    )


def test_join_records_before_submit_and_skips_a_new_reservation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.monitor.start as engine
    from sase.core.tool_run import tool_run_list
    from sase.tool.join_worker import join_worker_argv

    _lane(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENT_NAME", "acme")
    run_id = _reserve_detached("--", "true", agent="acme")
    captured: list[Any] = []
    monkeypatch.setattr(
        "sase.monitor.start_launch.submit_proc_request", _fake_submit_factory(captured)
    )
    _mock_claim(monkeypatch)
    before = tool_run_list({"schema_version": 1, "limit": 100}).get("runs") or []

    record = engine.start_monitor(_join_request(run_id, tmp_path, monkeypatch))

    assert record.tool_run_id == run_id
    assert record.tool_run_joined is True
    assert record.command == "sase tool run -- true"
    assert record.label == "tool:ad-hoc (joined)"
    assert record.reason == "finish ad-hoc (joined run)"
    assert len(captured) == 1
    assert list(captured[0].argv) == join_worker_argv(run_id)
    assert captured[0].env["SASE_MONITOR_ID"] == record.monitor_id
    assert captured[0].proc_id == record.monitor_id
    join = tool_run_show(run_id).get("run", {}).get("join")
    assert join["kind"] == "monitor"
    assert join["id"] == record.monitor_id
    meta = json.loads((Path(record.artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_tool_run_id"] == run_id
    assert meta["monitor_tool_run_joined"] is True
    after = tool_run_list({"schema_version": 1, "limit": 100}).get("runs") or []
    assert len(after) == len(before)


def test_join_duplicate_start_replays_without_resubmitting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.monitor.start as engine

    starter_dir = _lane(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENT_NAME", "acme")
    run_id = _reserve_detached("--", "true", agent="acme")
    captured: list[Any] = []
    monkeypatch.setattr(
        "sase.monitor.start_launch.submit_proc_request", _fake_submit_factory(captured)
    )
    _mock_claim(monkeypatch)
    # Continuation and policy resolution can legitimately re-fingerprint a
    # second identical construction; pin the identity like the ordinary
    # duplicate-start test does so the replay path itself is exercised. The
    # fake supervisor pid is dead by construction, so dead-supervisor
    # reconciliation is also held off: it owns ordinary liveness, not joins.
    monkeypatch.setattr(
        "sase.monitor.start_flow.monitor_request_fingerprint",
        lambda request, *, lane, label: "sha256:join-match",
    )
    monkeypatch.setattr(
        "sase.monitor.store_lane.should_reconcile_dead_supervisor",
        lambda *args, **kwargs: False,
    )
    request = _join_request(run_id, tmp_path, monkeypatch)
    first = engine.start_monitor(request)
    # The record fixture freezes the visible set: re-patch so the second
    # start sees the first monitor like the live index would.
    patch_project_records(monkeypatch, [starter_dir, first.artifacts_dir])
    second = engine.start_monitor(request)
    assert second.monitor_id == first.monitor_id
    assert len(captured) == 1


def test_join_submit_failure_releases_the_join_and_tears_down(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.monitor.start as engine
    from sase.monitor.models import MonitorError
    from sase.procs.submission import ProcSubmitError

    _lane(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENT_NAME", "acme")
    run_id = _reserve_detached("--", "true", agent="acme")

    def _boom(request: Any, *, after_spawn: Any, after_ack: Any) -> Any:
        raise ProcSubmitError("boom")

    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", _boom)
    with pytest.raises(MonitorError, match="boom"):
        engine.start_monitor(_join_request(run_id, tmp_path, monkeypatch))
    assert tool_run_show(run_id).get("run", {}).get("join") is None


def test_join_settle_race_tears_down_and_leaves_the_lane_clear(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.monitor.start as engine
    from sase.monitor.models import MonitorError

    _lane(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_AGENT_NAME", "acme")
    run_id = _reserve_detached("--", "true", agent="acme")
    # The run settles after validation passed but before the join records:
    # build the request the validated target would have carried.
    request = StartMonitorRequest(
        command="sase tool run -- true",
        reason="finish ad-hoc (joined run)",
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        start_status="TESTING",
        stop_status="TESTED",
        label="tool:ad-hoc (joined)",
        join_run_id=run_id,
    )
    _settle(run_id, state="succeeded", exit_code=0, terminal_cause="exited")
    captured: list[Any] = []
    monkeypatch.setattr(
        "sase.monitor.start_launch.submit_proc_request", _fake_submit_factory(captured)
    )
    _mock_claim(monkeypatch)
    with pytest.raises(MonitorError, match="already succeeded"):
        engine.start_monitor(request)
    assert tool_run_show(run_id).get("run", {}).get("join") is None
    # The refused member is torn down: a different command starts cleanly.
    plain = StartMonitorRequest(
        command="true",
        reason="verify",
        timeout_seconds=30.0,
        cwd=str(tmp_path),
        project_name="proj",
        start_status="TESTING",
        stop_status="TESTED",
        lane="acme",
    )
    record = engine.start_monitor(plain)
    assert record.monitor_state == "running"
    assert len(captured) == 1


# Tool stop routes a joined run through its active monitor.
def test_tool_stop_on_joined_run_stops_the_monitor_without_followup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.tool.control_stop import ToolStopCliRequest, handle_stop

    run_id = _reserve_detached("--", "sleep", "30", owner_id="proc-stop-join")
    joined = tool_run_join(
        {
            "schema_version": 1,
            "run_id": run_id,
            "joiner_kind": "monitor",
            "joiner_id": "mon-live",
            "agent": "agent-1",
        }
    )
    assert joined.get("outcome") == "joined"
    monkeypatch.setattr(
        "sase.tool.detach_cleanup.joined_monitor_active", lambda _run: "mon-live"
    )
    stopped: list[str] = []
    monkeypatch.setattr("sase.monitor.store.list_monitors", lambda **_: [])
    monkeypatch.setattr(
        "sase.monitor.store.resolve_monitor_ref",
        lambda _ref, _records: SimpleNamespace(monitor_id="mon-live"),
    )
    monkeypatch.setattr(
        "sase.monitor.store.stop_monitor",
        lambda record: (
            stopped.append(record.monitor_id)
            or SimpleNamespace(monitor_state="stopped")
        ),
    )
    code = handle_stop(ToolStopCliRequest(run_id=run_id, json=False))
    assert code == 0
    assert stopped == ["mon-live"]


def test_tool_stop_with_terminal_join_monitor_falls_back_to_the_proc_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.tool.control_stop import ToolStopCliRequest, handle_stop

    run_id = _reserve_detached("--", "sleep", "30", owner_id="proc-missing-owner")
    joined = tool_run_join(
        {
            "schema_version": 1,
            "run_id": run_id,
            "joiner_kind": "monitor",
            "joiner_id": "mon-gone",
            "agent": "agent-1",
        }
    )
    assert joined.get("outcome") == "joined"
    monkeypatch.setattr(
        "sase.tool.detach_cleanup.joined_monitor_active", lambda _run: None
    )

    def _no_monitor_stop(record: Any) -> Any:
        raise AssertionError("terminal joining monitors use the proc-owner path")

    monkeypatch.setattr("sase.monitor.store.stop_monitor", _no_monitor_stop)
    code = handle_stop(ToolStopCliRequest(run_id=run_id, json=False))
    assert code == 0
    assert capsys.readouterr().out.strip().endswith(("stop requested", "stopped"))
    stop = tool_run_show(run_id).get("run", {}).get("stop_request")
    assert isinstance(stop, dict)


# Settlement never adopts a joined run as monitor-owned.
def _settlement_state(tmp_path: Path, *, joined: bool) -> tuple[str, dict[str, Any]]:
    artifacts = tmp_path / "mon-settle"
    artifacts.mkdir(exist_ok=True)
    meta: dict[str, Any] = {
        "monitor_id": "mon-1",
        "monitor_tool_run_id": "run-1",
        "monitor_stop_status": "TESTED",
    }
    if joined:
        meta["monitor_tool_run_joined"] = True
    (artifacts / "agent_meta.json").write_text(json.dumps(meta))
    state: dict[str, Any] = {
        "artifacts_dir": str(artifacts),
        "proc_id": "mon-1",
        "status": "success",
        "termination_reason": "success",
        "exit_code": 0,
        "log_path": "",
    }
    return str(artifacts), state


def test_settle_skips_monitor_owned_reconcile_for_joined_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.monitor.proc_adapter as adapter

    _, state = _settlement_state(tmp_path, joined=True)
    reconciled: list[Any] = []
    monkeypatch.setattr(
        "sase.tool.settlement.settle_monitor_tool_run",
        lambda *args: reconciled.append(args),
    )
    monkeypatch.setattr(
        adapter,
        "settle_claim_and_followup",
        lambda *args, **kwargs: SimpleNamespace(error=None, launch_result=None),
    )
    monkeypatch.setattr(adapter, "write_agent_meta_atomic", lambda *a, **k: None)
    monkeypatch.setattr(
        adapter, "write_done_marker_and_update_index", lambda *a, **k: None
    )
    monkeypatch.setattr(adapter, "stamp_turn_finished_at", lambda marker: None)
    monkeypatch.setattr(adapter, "finalize_monitor_workflow_state", lambda *a: None)
    monkeypatch.setattr(adapter, "touch_monitor_refresh_pulse", lambda *a: None)
    monkeypatch.setattr(
        adapter, "publish_deferred_monitor_completion", lambda *a, **k: None
    )
    adapter.settle_monitor_followup(state)
    assert reconciled == []


def test_settle_still_reconciles_monitor_owned_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.monitor.proc_adapter as adapter

    _, state = _settlement_state(tmp_path, joined=False)
    reconciled: list[Any] = []
    monkeypatch.setattr(
        "sase.tool.settlement.settle_monitor_tool_run",
        lambda *args: reconciled.append(args),
    )
    monkeypatch.setattr(
        adapter,
        "settle_claim_and_followup",
        lambda *args, **kwargs: SimpleNamespace(error=None, launch_result=None),
    )
    monkeypatch.setattr(adapter, "write_agent_meta_atomic", lambda *a, **k: None)
    monkeypatch.setattr(
        adapter, "write_done_marker_and_update_index", lambda *a, **k: None
    )
    monkeypatch.setattr(adapter, "stamp_turn_finished_at", lambda marker: None)
    monkeypatch.setattr(adapter, "finalize_monitor_workflow_state", lambda *a: None)
    monkeypatch.setattr(adapter, "touch_monitor_refresh_pulse", lambda *a: None)
    monkeypatch.setattr(
        adapter, "publish_deferred_monitor_completion", lambda *a, **k: None
    )
    adapter.settle_monitor_followup(state)
    assert len(reconciled) == 1
    assert reconciled[0][0] == "run-1"
