"""E2 settlement: hand-off runs settle truthfully after crashes and deliver once."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest

from sase.config.core import clear_config_cache
from sase.core.process_identity import process_identity_token
from sase.core.tool_run import (
    tool_run_begin,
    tool_run_claim,
    tool_run_finish,
    tool_run_request_stop,
    tool_run_show,
)
from sase.notifications.store import load_notifications
from sase.procs import get_proc, new_proc_id, submit_proc_request, wait_for_proc
from sase.procs.models import Proc
from sase.procs.request import ProcSubmitRequest
from sase.procs.runtime import (
    proc_request_sidecar_path,
    write_json_atomic,
    write_termination_intent,
)
from sase.procs.settlement import settle_named_proc
from sase.procs.store import append_proc
from sase.tool.argv import resolve_run_argv
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.executor_recording import finish_tool_run
from sase.tool.handoff import (
    owner_request_fingerprint,
    owner_tags,
    reserve_handoff_run,
    worker_argv,
    worker_env_overlay,
)
from sase.tool.liveness import (
    _maybe_reap,
    current_boot_id,
    reconcile_handoff_run,
    reconcile_unsettled_tool_runs,
)
from sase.tool.notify import deliver_handoff_settlement
from sase.tool.owner import (
    observe_owner_fact,
    owner_fact_from_settlement,
    owner_retention,
)
from sase.tool.query import ToolShowCliRequest, handle_show
from sase.tool.settlement import settle_monitor_tool_run, settle_tool_run_followup

_DEAD_SUPERVISOR = "ffffeeee-dead-beef-0000-111122223333:1"


def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_MONITOR_ARTIFACTS_DIR",
        "SASE_PROC_ID",
        "SASE_PROC_LOG_PATH",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_EVENTS",
        "SASE_TOOL_RUN_AGENT",
        "SASE_BEAD_ID",
        "SASE_BEAD",
        "SASE_WORKSPACE_NUM",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clean_env(monkeypatch, tmp_path)


def _dead_identity() -> tuple[int, str, str]:
    """Return ``(pid, boot_id, identity)`` of a process that already exited."""

    finished = subprocess.Popen(["true"])
    finished.wait()
    boot = current_boot_id()
    return finished.pid, boot, f"{boot}:1"


def _reserve(
    owner_kind: str, owner_id: str, words: tuple[str, ...] = ("--", "true")
) -> str:
    reservation = reserve_handoff_run(
        resolve_run_argv(list(words)), owner_kind=owner_kind, owner_id=owner_id
    )
    assert reservation.reserved, reservation.error
    return reservation.run_id


def _reserve_with_dead_launcher(owner_id: str) -> str:
    """Reserve a ``created`` proc-owned run from a launcher that then exits."""

    code = (
        "import os\n"
        "from sase.tool.argv import resolve_run_argv\n"
        "from sase.tool.handoff import reserve_handoff_run\n"
        "r = reserve_handoff_run(resolve_run_argv(['--', 'true']), "
        f"owner_kind='proc', owner_id={owner_id!r})\n"
        "print(r.run_id, flush=True)\n"
        "os._exit(0)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env=dict(os.environ),
    )
    run_id = completed.stdout.strip()
    assert _run(run_id)["state"] == "created"
    return run_id


def _claim(
    run_id: str,
    owner_kind: str,
    owner_id: str,
    *,
    identity: tuple[int, str, str] | None = None,
    owner_log_path: str | None = None,
) -> None:
    pid, boot, token = identity or _dead_identity()
    request: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "owner_kind": owner_kind,
        "owner_id": owner_id,
        "wrapper_pid": pid,
        "boot_id": boot,
        "process_start_identity": token,
    }
    if owner_log_path is not None:
        request["owner_log_path"] = owner_log_path
    assert tool_run_claim(request)["outcome"] == "claimed"


def _run(run_id: str) -> dict[str, Any]:
    run = tool_run_show(run_id)["run"]
    assert isinstance(run, dict)
    return run


def _terminal(
    kind: str,
    owner_id: str,
    reason: str,
    *,
    exit_code: int | None = None,
    stop: bool = False,
) -> dict[str, Any]:
    fact: dict[str, Any] = {
        "kind": kind,
        "id": owner_id,
        "state": "terminal",
        "termination_reason": reason,
        "stop_requested": stop,
    }
    if exit_code is not None:
        fact["exit_code"] = exit_code
    return fact


def _result_reason(proc: Proc) -> object:
    assert isinstance(proc.result, dict)
    return proc.result["termination_reason"]


def _followup_of(proc: Proc) -> object:
    assert isinstance(proc.result, dict)
    return proc.result["followup"]


def _tool_run_notifications() -> list[Any]:
    return [
        item
        for item in load_notifications(include_dismissed=True)
        if item.sender == "tool-run"
    ]


def _expected_notification_id(run_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"sase:tool-run-settled:{run_id}"))


def _fabricate_proc(tmp_path: Path, proc_id: str, run_id: str | None) -> Proc:
    """Append a running named-proc row whose supervisor is gone."""

    proc = Proc(
        proc_id=proc_id,
        label="tool:test",
        kind="command",
        status="running",
        lifecycle="named-proc",
        command=["true"],
        argv=["true"],
        cwd=str(tmp_path),
        origin="tool-run",
        created_at="2026-07-25T12:00:00Z",
        log_path=str(tmp_path / f"{proc_id}.log"),
        request_fingerprint=f"tool-run:{run_id or proc_id}",
        reserved_by="test",
        supervisor_id=_DEAD_SUPERVISOR,
        pid=os.getpid(),
    )
    append_proc(proc)
    if run_id is not None:
        write_json_atomic(
            proc_request_sidecar_path(proc_id),
            {"followup": {"kind": "tool-run", "run_id": run_id}},
        )
    return proc


def _settle_fabricated(
    proc_id: str,
    *,
    status: str,
    reason: str,
    exit_code: int | None,
    message: str = "settled",
) -> Proc:
    return settle_named_proc(
        proc_id,
        supervisor_id=_DEAD_SUPERVISOR,
        status=status,
        message=message,
        termination_reason=reason,
        exit_code=exit_code,
    )


# --- Owner facts -----------------------------------------------------------


def test_owner_fact_only_for_proc_or_monitor_handoff_runs(tmp_path: Path) -> None:
    assert (
        observe_owner_fact({"launch_mode": "foreground", "owner_kind": "proc"}) is None
    )
    assert observe_owner_fact({"launch_mode": "handoff", "owner_kind": None}) is None
    assert observe_owner_fact({"launch_mode": "handoff", "owner_kind": "agent"}) is None
    missing = observe_owner_fact(
        {"launch_mode": "handoff", "owner_kind": "proc", "owner_id": "nope"}
    )
    assert missing == {"kind": "proc", "id": "nope", "state": "missing"}
    monitor = observe_owner_fact(
        {"launch_mode": "handoff", "owner_kind": "monitor", "owner_id": "mon-gone"}
    )
    assert monitor == {"kind": "monitor", "id": "mon-gone", "state": "missing"}


def test_owner_fact_reads_active_and_terminal_proc_rows(tmp_path: Path) -> None:
    _fabricate_proc(tmp_path, "proc-live", None)
    run = {"launch_mode": "handoff", "owner_kind": "proc", "owner_id": "proc-live"}
    assert observe_owner_fact(run) == {
        "kind": "proc",
        "id": "proc-live",
        "state": "active",
    }
    _settle_fabricated("proc-live", status="error", reason="error", exit_code=3)
    fact = observe_owner_fact(run)
    assert fact == {
        "kind": "proc",
        "id": "proc-live",
        "state": "terminal",
        "exit_code": 3,
        "termination_reason": "error",
        "stop_requested": False,
    }


def test_owner_fact_from_settlement_honors_stop_intent() -> None:
    state = {"exit_code": None, "termination_reason": "stop", "stop_requested": True}
    fact = owner_fact_from_settlement("proc", "p1", state)
    assert fact["state"] == "terminal"
    assert fact["termination_reason"] == "stop"
    assert fact["stop_requested"] is True
    assert "exit_code" not in fact

    write_termination_intent("p2", "stop")
    intent = owner_fact_from_settlement(
        "proc", "p2", {"exit_code": 143, "termination_reason": "error"}
    )
    assert intent["stop_requested"] is True
    assert intent["exit_code"] == 143

    plain = owner_fact_from_settlement(
        "monitor", "p3", {"exit_code": 0, "termination_reason": "success"}
    )
    assert plain["kind"] == "monitor"
    assert plain["stop_requested"] is False


# --- Reconcile rows (epic test matrix) -------------------------------------


def test_launcher_killed_after_reservation_settles_launch_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 1: a launcher that dies before submit leaves no owner and no command."""

    run_id = _reserve_with_dead_launcher(new_proc_id())

    reconcile_unsettled_tool_runs()

    run = _run(run_id)
    assert run["state"] == "failed"
    assert run["terminal_cause"] == "launch_failed"
    assert "command was not run" in run["diagnostics"]
    assert run.get("exit_code") is None


def test_created_run_with_live_launcher_is_not_settled() -> None:
    run_id = _reserve("proc", "proc-not-yet-submitted")
    reconcile_unsettled_tool_runs()
    assert _run(run_id)["state"] == "created"


def test_dead_launcher_alone_is_never_proof(tmp_path: Path) -> None:
    """A created run whose launcher exited but whose owner is active stays created."""

    run_id = _reserve("proc", "proc-active-owner")
    _fabricate_proc(tmp_path, "proc-active-owner", run_id)
    run = _run(run_id)
    dead = _dead_identity()
    launcher = {
        "pid": dead[0],
        "boot_id": dead[1],
        "process_start_identity": dead[2],
    }
    from sase.tool.liveness import _liveness_fact

    fact = _liveness_fact({**run, "launcher": launcher}, observe_owner_fact(run))
    assert fact["observation"] == "unknown"
    assert fact["owner"]["state"] == "active"
    result = reconcile_handoff_run(
        run_id, {"kind": "proc", "id": "proc-active-owner", "state": "active"}
    )
    assert not result["settled"]
    assert _run(run_id)["state"] == "created"


def test_worker_dies_owner_settles_exit_recovers_from_owner(tmp_path: Path) -> None:
    """Row 3: worker gone while the owner runs; the owner's exit code settles it."""

    run_id = _reserve("proc", "proc-3")
    _claim(run_id, "proc", "proc-3")
    active = {"kind": "proc", "id": "proc-3", "state": "active"}
    assert not reconcile_handoff_run(run_id, active)["settled"]
    assert _run(run_id)["state"] == "running"

    result = reconcile_handoff_run(
        run_id, _terminal("proc", "proc-3", "error", exit_code=3)
    )

    assert [item["run_id"] for item in result["settled"]] == [run_id]
    run = _run(run_id)
    assert run["state"] == "failed"
    assert run["exit_code"] == 3
    assert run["settled_by"] == "owner"
    assert run["terminal_cause"] == "exited"
    assert any("recovered from owner result" in item for item in run["diagnostics"])


def test_worker_sigkilled_by_signal_is_lost_not_success() -> None:
    """Row 3b: a negative owner exit code never fabricates a result."""

    run_id = _reserve("proc", "proc-3b")
    _claim(run_id, "proc", "proc-3b")

    reconcile_handoff_run(run_id, _terminal("proc", "proc-3b", "error", exit_code=-9))

    run = _run(run_id)
    assert run["state"] == "lost"
    assert run["terminal_cause"] == "owner_lost"
    assert run.get("exit_code") is None


@pytest.mark.parametrize("reason", ["supervisor-loss", "launch-failure"])
def test_supervisor_loss_settles_lost_without_rerun(reason: str) -> None:
    """Row 4: no rerun and no exit code when the supervisor vanished."""

    run_id = _reserve("proc", "proc-4")
    _claim(run_id, "proc", "proc-4")
    reconcile_handoff_run(run_id, _terminal("proc", "proc-4", reason))
    run = _run(run_id)
    assert run["state"] == "lost"
    assert run["terminal_cause"] == "owner_lost"


def test_reboot_with_boot_id_mismatch_settles_lost_without_rerun() -> None:
    """Row 10: a stale-boot worker identity plus a reboot owner fact is lost."""

    run_id = _reserve("proc", "proc-10")
    _claim(
        run_id,
        "proc",
        "proc-10",
        identity=(
            os.getpid(),
            "boot-from-before-the-reboot",
            "boot-from-before-the-reboot:1",
        ),
    )

    reconcile_handoff_run(run_id, _terminal("proc", "proc-10", "reboot"))

    run = _run(run_id)
    assert run["state"] == "lost"
    assert run["terminal_cause"] == "owner_lost"
    assert run.get("exit_code") is None
    assert _run(run_id)["launch_mode"] == "handoff"


@pytest.mark.parametrize("reason", ["total-timeout", "idle-timeout"])
def test_owner_timeout_settles_signaled_timeout(reason: str) -> None:
    run_id = _reserve("proc", "proc-5")
    _claim(run_id, "proc", "proc-5")
    reconcile_handoff_run(run_id, _terminal("proc", "proc-5", reason))
    run = _run(run_id)
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "timeout"


def test_stop_before_the_barrier_settles_stop_requested_command_not_run() -> None:
    """Row 6: a stopped proc never started the command."""

    run_id = _reserve_with_dead_launcher("proc-6")
    tool_run_request_stop(
        {"schema_version": 1, "run_id": run_id, "requested_by": "test"}
    )
    reconcile_handoff_run(
        run_id, _terminal("proc", "proc-6", "stop", exit_code=None, stop=True)
    )
    run = _run(run_id)
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "stop_requested"
    assert "command was not run" in run["diagnostics"]


def test_reconcile_handoff_run_never_raises_and_ignores_foreground(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unknown = reconcile_handoff_run(
        "0" * 32, {"kind": "proc", "id": "x", "state": "missing"}
    )
    assert unknown["settled"] == []
    foreground = tool_run_begin(
        {
            "schema_version": 1,
            "definition": {
                "schema_version": 1,
                "name": "ad-hoc",
                "argv": ["true"],
                "description": "",
                "stages": "none",
                "inputs": [],
                "env": [],
                "args": "allow",
                "fingerprint": {"repos": [], "toolchain": {}},
            },
            "display_argv": ["true"],
            "project": "fixture",
            "commit_running": True,
            "wrapper_pid": _dead_identity()[0],
            "boot_id": current_boot_id() or None,
            "process_start_identity": f"{current_boot_id()}:1",
        }
    )["run"]["run_id"]
    result = reconcile_handoff_run(
        foreground, {"kind": "proc", "id": "x", "state": "missing"}
    )
    assert result["settled"] == []
    assert _run(foreground)["state"] == "running"

    monkeypatch.setattr(
        "sase.tool.liveness.tool_run_show",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("store exploded")),
    )
    failed = reconcile_handoff_run(foreground, None)
    assert failed["persisted"] is False
    assert "store exploded" in failed["diagnostics"][0]


# --- Reap guard -------------------------------------------------------------


def test_maybe_reap_never_signals_an_owned_runs_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Row 11: even if core emitted a candidate, an owned run is never signaled."""

    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))
    result = {
        "reap_candidates": [
            {
                "run_id": "owned-run",
                "pgid": 424242,
                "child_process_start_identity": "boot:1",
            }
        ],
        "diagnostics": [],
    }

    reaped = _maybe_reap(result, reap_orphans=True, owned_run_ids={"owned-run"})

    assert calls == []
    assert any(
        "owned-run" in item and "has an owner" in item for item in reaped["diagnostics"]
    )


# --- Finish race ------------------------------------------------------------


def test_finish_tool_run_treats_an_already_settled_run_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = _reserve("proc", "proc-7")
    _claim(run_id, "proc", "proc-7")
    reconcile_handoff_run(run_id, _terminal("proc", "proc-7", "error", exit_code=2))
    assert _run(run_id)["state"] == "failed"

    assert finish_tool_run(
        run_id,
        state="failed",
        exit_code=2,
        duration_ms=5,
        terminal_cause="exited",
    )

    def busy(_payload: dict[str, Any]) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr("sase.tool.executor_recording.tool_run_finish", busy)
    assert finish_tool_run(run_id, state="failed", exit_code=2, duration_ms=5)


def test_finish_tool_run_still_fails_when_the_run_is_unsettled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = _reserve("proc", "proc-7b")
    _claim(run_id, "proc", "proc-7b")

    def busy(_payload: dict[str, Any]) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr("sase.tool.executor_recording.tool_run_finish", busy)
    assert not finish_tool_run(run_id, state="failed", exit_code=2, duration_ms=5)


def test_failed_worker_finish_is_recovered_through_the_settlement_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 7: a worker whose finish raised is settled from the owner's result."""

    run_id = _reserve("proc", "proc-7c")
    _claim(run_id, "proc", "proc-7c")
    _fabricate_proc(tmp_path, "proc-7c", run_id)

    def busy(_payload: dict[str, Any]) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr("sase.tool.executor_recording.tool_run_finish", busy)
    assert not finish_tool_run(run_id, state="failed", exit_code=3, duration_ms=5)
    monkeypatch.undo()
    _clean_env(monkeypatch, tmp_path)
    assert _run(run_id)["state"] == "running"

    _settle_fabricated("proc-7c", status="error", reason="error", exit_code=3)

    run = _run(run_id)
    assert run["state"] == "failed"
    assert run["exit_code"] == 3
    assert run["settled_by"] == "owner"
    assert len(_tool_run_notifications()) == 1


# --- Proc settlement hook ---------------------------------------------------


def test_proc_settlement_hook_settles_run_and_publishes_once(tmp_path: Path) -> None:
    run_id = _reserve("proc", "proc-hook")
    _claim(run_id, "proc", "proc-hook")
    _fabricate_proc(tmp_path, "proc-hook", run_id)

    finished = _settle_fabricated(
        "proc-hook", status="error", reason="error", exit_code=3
    )

    assert finished.status == "error"
    assert _followup_of(finished) == "tool-run-settled"
    run = _run(run_id)
    assert (run["state"], run["exit_code"], run["settled_by"]) == ("failed", 3, "owner")
    notifications = _tool_run_notifications()
    assert [item.id for item in notifications] == [_expected_notification_id(run_id)]
    note = notifications[0]
    assert note.sender == "tool-run"
    assert note.tags == ["tool-run"]
    assert note.action is None
    assert note.action_data == {
        "run_id": run_id,
        "command": f"sase tool show {run_id}",
    }
    assert f"sase tool show {run_id}" in note.notes
    assert note.notes[0].startswith("Tool run ad-hoc failed")
    assert "(exit 3)" in note.notes[0]


def test_supervisor_loss_via_proc_reconcile_settles_lost(tmp_path: Path) -> None:
    """Row 4 end to end: a supervisor that died is reconciled, the run is lost."""

    from sase.procs import reconcile_running_procs

    run_id = _reserve("proc", "proc-loss")
    _claim(run_id, "proc", "proc-loss")
    _fabricate_proc(tmp_path, "proc-loss", run_id)

    reconcile_running_procs()

    proc = get_proc("proc-loss")
    assert proc is not None and proc.status == "error"
    run = _run(run_id)
    assert run["state"] == "lost"
    assert run["terminal_cause"] == "owner_lost"
    assert len(_tool_run_notifications()) == 1


def test_stopped_proc_before_start_settles_via_hook(tmp_path: Path) -> None:
    run_id = _reserve_with_dead_launcher("proc-stop")
    _fabricate_proc(tmp_path, "proc-stop", run_id)

    _settle_fabricated(
        "proc-stop",
        status="killed",
        reason="stop",
        exit_code=None,
        message="proc killed",
    )

    run = _run(run_id)
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "stop_requested"
    assert "command was not run" in run["diagnostics"]


def test_settlement_hook_errors_still_finish_the_proc_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 12: a ToolRun or notification error never wedges proc settlement."""

    run_id = _reserve("proc", "proc-wedge")
    _claim(run_id, "proc", "proc-wedge")
    _fabricate_proc(tmp_path, "proc-wedge", run_id)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("reconcile exploded")

    monkeypatch.setattr("sase.tool.settlement.reconcile_handoff_run", boom)
    finished = _settle_fabricated(
        "proc-wedge", status="error", reason="error", exit_code=3
    )

    assert finished.status == "error"
    assert _followup_of(finished) == "tool-run-error"
    assert _run(run_id)["state"] == "running"


def test_settlement_hook_import_or_outer_errors_are_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = _reserve("proc", "proc-wedge2")
    _fabricate_proc(tmp_path, "proc-wedge2", run_id)

    def boom(_state: dict[str, Any]) -> None:
        raise RuntimeError("hook exploded")

    monkeypatch.setattr("sase.tool.settlement.settle_tool_run_followup", boom)
    finished = _settle_fabricated(
        "proc-wedge2", status="error", reason="error", exit_code=3
    )
    assert finished.status == "error"
    assert _followup_of(finished) == "tool-run-error"


def test_notification_failure_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = _reserve("proc", "proc-notify-fail")
    _claim(run_id, "proc", "proc-notify-fail")
    monkeypatch.setattr(
        "sase.notifications.store.append_notification",
        lambda _n: (_ for _ in ()).throw(OSError("disk full")),
    )
    state: dict[str, Any] = {
        "proc_id": "proc-notify-fail",
        "exit_code": 3,
        "termination_reason": "error",
        "followup": {"kind": "tool-run", "run_id": run_id},
    }
    settle_tool_run_followup(state)
    assert _run(run_id)["state"] == "failed"
    assert state["followup_outcome"] == "tool-run-error"
    assert "notification failed" in state["followup_error"]


# --- Deliver once -----------------------------------------------------------


def test_repeated_passes_and_resumed_settlement_publish_exactly_once(
    tmp_path: Path,
) -> None:
    """Row 8: hook twice, worker delivery, and reconcile passes collapse to one."""

    run_id = _reserve("proc", "proc-once")
    _claim(run_id, "proc", "proc-once")
    state: dict[str, Any] = {
        "proc_id": "proc-once",
        "exit_code": 3,
        "termination_reason": "error",
        "followup": {"kind": "tool-run", "run_id": run_id},
    }

    settle_tool_run_followup(state)
    assert state["followup_outcome"] == "tool-run-settled"
    settle_tool_run_followup(state)
    assert state["followup_outcome"] == "tool-run-settled"
    assert deliver_handoff_settlement(run_id) == "already_published"
    assert deliver_handoff_settlement(_run(run_id)) == "already_published"
    reconcile_unsettled_tool_runs()
    reconcile_unsettled_tool_runs(reap_orphans=True)

    notifications = _tool_run_notifications()
    assert [item.id for item in notifications] == [_expected_notification_id(run_id)]


def test_reconcile_pass_that_settles_a_proc_owned_run_delivers(
    tmp_path: Path,
) -> None:
    """A reconcile pass (e.g. ``tool show``) delivers for a run it settled."""

    run_id = _reserve("proc", "proc-pass")
    _claim(run_id, "proc", "proc-pass")
    # No proc row: the owner is missing and the worker identity is dead.
    reconcile_unsettled_tool_runs()
    reconcile_unsettled_tool_runs()
    assert _run(run_id)["state"] == "lost"
    assert [item.id for item in _tool_run_notifications()] == [
        _expected_notification_id(run_id)
    ]


def test_monitor_owned_runs_produce_no_notification(tmp_path: Path) -> None:
    run_id = _reserve("monitor", "mon-1")
    _claim(run_id, "monitor", "mon-1")
    settle_monitor_tool_run(
        run_id, "mon-1", {"exit_code": 3, "termination_reason": "error"}
    )
    run = _run(run_id)
    assert (run["state"], run["exit_code"], run["settled_by"]) == ("failed", 3, "owner")
    assert deliver_handoff_settlement(run_id) == "skipped"
    reconcile_unsettled_tool_runs()
    assert _tool_run_notifications() == []


def test_delivery_skips_unsettled_foreground_and_unknown_runs() -> None:
    run_id = _reserve("proc", "proc-skip")
    assert deliver_handoff_settlement(run_id) == "skipped"
    assert deliver_handoff_settlement("0" * 32) == "skipped"
    assert (
        deliver_handoff_settlement({"run_id": "x", "state": "succeeded"}) == "skipped"
    )
    assert _tool_run_notifications() == []


def test_notification_carries_owner_log_when_it_exists(tmp_path: Path) -> None:
    log = tmp_path / "owner.log"
    log.write_text("output\n", encoding="utf-8")
    run_id = _reserve("proc", "proc-log")
    _claim(run_id, "proc", "proc-log", owner_log_path=str(log))
    settle_tool_run_followup(
        {
            "proc_id": "proc-log",
            "exit_code": 0,
            "termination_reason": "success",
            "followup": {"kind": "tool-run", "run_id": run_id},
        }
    )
    (note,) = _tool_run_notifications()
    assert note.files == [str(log)]
    assert note.notes[0].startswith("Tool run ad-hoc succeeded")


# --- Retention reporting ----------------------------------------------------


def test_pruned_owner_is_reported_by_show_json_and_logs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Row 9: the summary stays intact and the missing log is named."""

    gone_log = str(tmp_path / "pruned-owner.log")
    run_id = _reserve("proc", "proc-pruned")
    _claim(run_id, "proc", "proc-pruned", owner_log_path=gone_log)

    assert handle_show(ToolShowCliRequest(run_id=run_id, json=True, logs=False)) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["owner_retention"] == {
        "owner": "pruned",
        "log": "missing",
        "log_path": gone_log,
    }
    assert envelope["run"]["run_id"] == run_id
    assert envelope["run"]["state"] == "lost"
    assert envelope["run"]["display_argv"] == ["true"]

    assert handle_show(ToolShowCliRequest(run_id=run_id, json=False, logs=True)) == 0
    err = capsys.readouterr().err
    assert "proc owner proc-pruned is no longer retained (pruned)" in err
    assert f"its log {gone_log} is missing" in err

    assert handle_show(ToolShowCliRequest(run_id=run_id, json=False, logs=False)) == 0
    out = capsys.readouterr().out
    assert "OWNERRET  proc proc-pruned: pruned; log not retained" in out


def test_pruned_owner_recorded_log_still_replays(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "kept.log"
    log.write_text("kept output\n", encoding="utf-8")
    run_id = _reserve("proc", "proc-pruned-kept")
    _claim(run_id, "proc", "proc-pruned-kept", owner_log_path=str(log))

    assert handle_show(ToolShowCliRequest(run_id=run_id, json=False, logs=True)) == 0
    captured = capsys.readouterr()
    assert "kept output" in captured.out


def test_follow_states_that_a_pruned_owner_has_no_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gone_log = str(tmp_path / "gone.log")
    run_id = _reserve("proc", "proc-follow")
    _claim(run_id, "proc", "proc-follow", owner_log_path=gone_log)

    code = handle_show(
        ToolShowCliRequest(run_id=run_id, json=True, logs=False, follow=True)
    )

    assert code == 0
    captured = capsys.readouterr()
    assert captured.err.count("no longer retained") == 1
    assert json.loads(captured.out)["owner_retention"]["owner"] == "pruned"


def test_owner_retention_states(tmp_path: Path) -> None:
    assert owner_retention({"launch_mode": "foreground"}) == {
        "owner": "none",
        "log": "none",
        "log_path": None,
    }
    _fabricate_proc(tmp_path, "proc-kept", None)
    run = {"owner_kind": "proc", "owner_id": "proc-kept", "logs": {}}
    live = owner_retention(run)
    assert live["owner"] == "retained"
    assert live["log"] == "missing"
    assert live["log_path"] == str(tmp_path / "proc-kept.log")
    (tmp_path / "proc-kept.log").write_text("x", encoding="utf-8")
    assert owner_retention(run)["log"] == "retained"
    unrecorded = owner_retention(
        {"owner_kind": "proc", "owner_id": "proc-never-existed", "logs": {}}
    )
    assert unrecorded == {"owner": "pruned", "log": "not-recorded", "log_path": None}


def test_persisted_diagnostics_render_in_show_json_and_human(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """sase-145: finish diagnostics are visible in ``show -j`` and the DIAG block."""

    run_id = _reserve("proc", "proc-diag")
    _claim(
        run_id,
        "proc",
        "proc-diag",
        identity=(os.getpid(), current_boot_id(), process_identity_token(os.getpid())),
    )
    tool_run_finish(
        {
            "schema_version": 1,
            "run_id": run_id,
            "state": "failed",
            "exit_code": 127,
            "duration_ms": 5,
            "terminal_cause": "exited",
            "diagnostics": ["spawn failed: executable not found: nope"],
        }
    )

    assert handle_show(ToolShowCliRequest(run_id=run_id, json=True, logs=False)) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert "spawn failed: executable not found: nope" in envelope["run"]["diagnostics"]

    assert handle_show(ToolShowCliRequest(run_id=run_id, json=False, logs=False)) == 0
    out = capsys.readouterr().out
    assert "DIAG\n  spawn failed: executable not found: nope" in out


# --- Real supervisor: termination intent and timeouts -----------------------


def _submit_worker(
    tmp_path: Path,
    words: tuple[str, ...],
    *,
    timeout_seconds: int | None = None,
    idle_timeout_seconds: int | None = None,
) -> tuple[str, str]:
    proc_id = new_proc_id()
    run_id = _reserve("proc", proc_id, words)
    submit_proc_request(
        ProcSubmitRequest(
            argv=worker_argv(run_id),
            command=["sase", "tool", "run", *words],
            label="tool:ad-hoc",
            cwd=tmp_path,
            origin="tool-run",
            proc_id=proc_id,
            tags=owner_tags(run_id),
            env=worker_env_overlay(),
            request_fingerprint=owner_request_fingerprint(run_id),
            followup={"kind": "tool-run", "run_id": run_id},
            timeout_seconds=timeout_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
        )
    )
    return run_id, proc_id


def _settled_run(run_id: str, *, timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = _run(run_id)
        if run["state"] not in ("created", "running"):
            return run
        time.sleep(0.2)  # sase-test-wait: poll worker or hook settlement
    pytest.fail(f"run {run_id} did not settle")


def test_total_timeout_settles_signaled_timeout(tmp_path: Path) -> None:
    """Row 5: a real supervisor's total timeout is a timeout, not a bare signal."""

    run_id, proc_id = _submit_worker(tmp_path, ("--", "sleep", "30"), timeout_seconds=1)
    proc = wait_for_proc(proc_id, timeout=60)
    assert _result_reason(proc) == "total-timeout"
    run = _settled_run(run_id)
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "timeout"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not _tool_run_notifications():
        time.sleep(0.2)  # sase-test-wait: poll notification durability
    assert [item.id for item in _tool_run_notifications()] == [
        _expected_notification_id(run_id)
    ]


def test_idle_timeout_settles_signaled_timeout(tmp_path: Path) -> None:
    run_id, proc_id = _submit_worker(
        tmp_path,
        ("--", "sh", "-c", "echo started; sleep 30"),
        idle_timeout_seconds=1,
    )
    proc = wait_for_proc(proc_id, timeout=60)
    assert _result_reason(proc) == "idle-timeout"
    run = _settled_run(run_id)
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "timeout"


def test_handoff_end_to_end_publishes_one_notification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Row 2: the launcher exits after submit and the worker settles the run."""

    request = ToolRunCliRequest(
        quiet=True,
        verbose=False,
        tail_lines=200,
        words=("--", "sh", "-c", "exit 0"),
        hand_off=True,
        tail_lines_explicit=False,
    )
    assert execute_tool_run(request) == 0
    run_id = capsys.readouterr().out.strip()
    run = _settled_run(run_id)
    assert run["state"] == "succeeded"
    assert run["settled_by"] != "owner"
    proc_id = run["owner_id"]
    wait_for_proc(proc_id, timeout=60)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not _tool_run_notifications():
        time.sleep(0.2)  # sase-test-wait: poll notification durability
    reconcile_unsettled_tool_runs()
    assert [item.id for item in _tool_run_notifications()] == [
        _expected_notification_id(run_id)
    ]


def test_supervisor_sigterm_records_stop_intent_worker_settles_stop(
    tmp_path: Path,
) -> None:
    run_id, proc_id = _submit_worker(tmp_path, ("--", "sleep", "30"))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and _run(run_id)["state"] != "running":
        time.sleep(0.1)  # sase-test-wait: poll worker claim
    assert _run(run_id)["state"] == "running"
    proc = get_proc(proc_id)
    assert proc is not None and proc.pid is not None
    os.kill(proc.pid, signal.SIGTERM)
    wait_for_proc(proc_id, timeout=60)
    run = _settled_run(run_id)
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "stop_requested"
