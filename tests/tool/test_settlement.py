"""E2 settlement: hand-off runs settle truthfully after crashes and deliver once."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.core.tool_run import tool_run_begin, tool_run_request_stop
from sase.procs import new_proc_id
from sase.procs.runtime import write_termination_intent
from sase.tool.liveness import (
    _maybe_reap,
    current_boot_id,
    reconcile_handoff_run,
    reconcile_unsettled_tool_runs,
)
from sase.tool.owner import observe_owner_fact, owner_fact_from_settlement
from tool._settlement_helpers import (
    claim,
    clean_env,
    dead_identity,
    fabricate_proc,
    get_run,
    reserve,
    reserve_with_dead_launcher,
    settle_fabricated,
    terminal_fact,
)


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clean_env(monkeypatch, tmp_path)


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
    fabricate_proc(tmp_path, "proc-live", None)
    run = {"launch_mode": "handoff", "owner_kind": "proc", "owner_id": "proc-live"}
    assert observe_owner_fact(run) == {
        "kind": "proc",
        "id": "proc-live",
        "state": "active",
    }
    settle_fabricated("proc-live", status="error", reason="error", exit_code=3)
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

    run_id = reserve_with_dead_launcher(new_proc_id())

    reconcile_unsettled_tool_runs()

    run = get_run(run_id)
    assert run["state"] == "failed"
    assert run["terminal_cause"] == "launch_failed"
    assert "command was not run" in run["diagnostics"]
    assert run.get("exit_code") is None


def test_created_run_with_live_launcher_is_not_settled() -> None:
    run_id = reserve("proc", "proc-not-yet-submitted")
    reconcile_unsettled_tool_runs()
    assert get_run(run_id)["state"] == "created"


def test_dead_launcher_alone_is_never_proof(tmp_path: Path) -> None:
    """A created run whose launcher exited but whose owner is active stays created."""

    run_id = reserve("proc", "proc-active-owner")
    fabricate_proc(tmp_path, "proc-active-owner", run_id)
    run = get_run(run_id)
    dead = dead_identity()
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
    assert get_run(run_id)["state"] == "created"


def test_worker_dies_owner_settles_exit_recovers_from_owner(tmp_path: Path) -> None:
    """Row 3: worker gone while the owner runs; the owner's exit code settles it."""

    run_id = reserve("proc", "proc-3")
    claim(run_id, "proc", "proc-3")
    active = {"kind": "proc", "id": "proc-3", "state": "active"}
    assert not reconcile_handoff_run(run_id, active)["settled"]
    assert get_run(run_id)["state"] == "running"

    result = reconcile_handoff_run(
        run_id, terminal_fact("proc", "proc-3", "error", exit_code=3)
    )

    assert [item["run_id"] for item in result["settled"]] == [run_id]
    run = get_run(run_id)
    assert run["state"] == "failed"
    assert run["exit_code"] == 3
    assert run["settled_by"] == "owner"
    assert run["terminal_cause"] == "exited"
    assert any("recovered from owner result" in item for item in run["diagnostics"])


def test_worker_sigkilled_by_signal_is_lost_not_success() -> None:
    """Row 3b: a negative owner exit code never fabricates a result."""

    run_id = reserve("proc", "proc-3b")
    claim(run_id, "proc", "proc-3b")

    reconcile_handoff_run(
        run_id, terminal_fact("proc", "proc-3b", "error", exit_code=-9)
    )

    run = get_run(run_id)
    assert run["state"] == "lost"
    assert run["terminal_cause"] == "owner_lost"
    assert run.get("exit_code") is None


@pytest.mark.parametrize("reason", ["supervisor-loss", "launch-failure"])
def test_supervisor_loss_settles_lost_without_rerun(reason: str) -> None:
    """Row 4: no rerun and no exit code when the supervisor vanished."""

    run_id = reserve("proc", "proc-4")
    claim(run_id, "proc", "proc-4")
    reconcile_handoff_run(run_id, terminal_fact("proc", "proc-4", reason))
    run = get_run(run_id)
    assert run["state"] == "lost"
    assert run["terminal_cause"] == "owner_lost"


def test_reboot_with_boot_id_mismatch_settles_lost_without_rerun() -> None:
    """Row 10: a stale-boot worker identity plus a reboot owner fact is lost."""

    run_id = reserve("proc", "proc-10")
    claim(
        run_id,
        "proc",
        "proc-10",
        identity=(
            os.getpid(),
            "boot-from-before-the-reboot",
            "boot-from-before-the-reboot:1",
        ),
    )

    reconcile_handoff_run(run_id, terminal_fact("proc", "proc-10", "reboot"))

    run = get_run(run_id)
    assert run["state"] == "lost"
    assert run["terminal_cause"] == "owner_lost"
    assert run.get("exit_code") is None
    assert get_run(run_id)["launch_mode"] == "handoff"


@pytest.mark.parametrize("reason", ["total-timeout", "idle-timeout"])
def test_owner_timeout_settles_signaled_timeout(reason: str) -> None:
    run_id = reserve("proc", "proc-5")
    claim(run_id, "proc", "proc-5")
    reconcile_handoff_run(run_id, terminal_fact("proc", "proc-5", reason))
    run = get_run(run_id)
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "timeout"


def test_stop_before_the_barrier_settles_stop_requested_command_not_run() -> None:
    """Row 6: a stopped proc never started the command."""

    run_id = reserve_with_dead_launcher("proc-6")
    tool_run_request_stop(
        {"schema_version": 1, "run_id": run_id, "requested_by": "test"}
    )
    reconcile_handoff_run(
        run_id, terminal_fact("proc", "proc-6", "stop", exit_code=None, stop=True)
    )
    run = get_run(run_id)
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
            "wrapper_pid": dead_identity()[0],
            "boot_id": current_boot_id() or None,
            "process_start_identity": f"{current_boot_id()}:1",
        }
    )["run"]["run_id"]
    result = reconcile_handoff_run(
        foreground, {"kind": "proc", "id": "x", "state": "missing"}
    )
    assert result["settled"] == []
    assert get_run(foreground)["state"] == "running"

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
