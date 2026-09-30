"""Join start transaction, tool-stop routing, and settlement for joined runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.core.tool_run import tool_run_join, tool_run_show
from sase.monitor.request import StartMonitorRequest
from sase.running_field import WorkspaceClaim
from tests.monitor._fixtures import (
    make_starter_agent,
    patch_project_records,
    write_project_file,
)

from ._join_helpers import (
    join_env as join_env,
    reserve_detached_run,
    settle_detached_run,
)

__all__ = [
    "test_join_duplicate_start_replays_without_resubmitting",
    "test_join_records_before_submit_and_skips_a_new_reservation",
    "test_join_settle_race_tears_down_and_leaves_the_lane_clear",
    "test_join_submit_failure_releases_the_join_and_tears_down",
    "test_settle_skips_monitor_owned_reconcile_for_joined_runs",
    "test_settle_still_reconciles_monitor_owned_runs",
    "test_tool_stop_on_joined_run_stops_the_monitor_without_followup",
    "test_tool_stop_with_terminal_join_monitor_falls_back_to_the_proc_path",
]


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
    run_id = reserve_detached_run("--", "true", agent="acme")
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
    run_id = reserve_detached_run("--", "true", agent="acme")
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
    run_id = reserve_detached_run("--", "true", agent="acme")

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
    run_id = reserve_detached_run("--", "true", agent="acme")
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
    settle_detached_run(run_id, state="succeeded", exit_code=0, terminal_cause="exited")
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

    run_id = reserve_detached_run("--", "sleep", "30", owner_id="proc-stop-join")
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

    run_id = reserve_detached_run("--", "sleep", "30", owner_id="proc-missing-owner")
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
