from __future__ import annotations

import os
from pathlib import Path
import subprocess

from sase.core.process_identity import process_identity_token
from sase.core.tool_run import tool_run_begin, tool_run_show
from sase.tool.liveness import (
    current_boot_id,
    _liveness_fact,
    _observe_launcher,
    _observe_wrapper,
    reconcile_unsettled_tool_runs,
)


def _definition() -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "ad-hoc",
        "argv": ["true"],
        "description": "",
        "stages": "none",
        "inputs": [],
        "env": [],
        "args": "allow",
        "fingerprint": {"repos": [], "toolchain": {}},
    }


def _begin(store: str, **overrides: object) -> str:
    payload = {
        "schema_version": 1,
        "definition": _definition(),
        "display_argv": ["true"],
        "project": "fixture",
        "commit_running": True,
        "wrapper_pid": os.getpid(),
        "boot_id": current_boot_id() or None,
        "process_start_identity": process_identity_token(os.getpid()) or None,
    }
    payload.update(overrides)
    started = tool_run_begin(payload, store_path=store)
    return str(started["run"]["run_id"])


def test_dead_wrapper_is_marked_lost(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    store = str(tmp_path / "home" / "tools" / "runs.sqlite")
    finished = subprocess.Popen(["true"])
    finished.wait()
    run_id = _begin(
        store,
        wrapper_pid=finished.pid,
        process_start_identity=f"{current_boot_id()}:1",
    )
    result = reconcile_unsettled_tool_runs()
    assert run_id in result.get("marked_lost", [])
    shown = tool_run_show(run_id, store_path=store)
    assert shown["run"]["state"] == "lost"
    assert shown["run"]["lost_reason"] == "runner exited without settling"
    assert shown["run"].get("duration_ms") is None
    assert shown["run"].get("exit_code") is None


def test_pid_reuse_is_dead(tmp_path: Path) -> None:
    run = {
        "run_id": "r1",
        "wrapper_pid": os.getpid(),
        "boot_id": current_boot_id(),
        "process_start_identity": f"{current_boot_id()}:1",
    }
    fact = _observe_wrapper(run)
    assert fact["observation"] == "dead"


def test_missing_wrapper_pid_is_unknown() -> None:
    fact = _observe_wrapper({"run_id": "r2", "wrapper_pid": None})
    assert fact["observation"] == "unknown"
    assert "not recorded" in str(fact.get("reason") or "")


def test_alive_wrapper_is_not_lost(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    store = str(tmp_path / "home" / "tools" / "runs.sqlite")
    run_id = _begin(store)
    result = reconcile_unsettled_tool_runs()
    assert run_id not in result.get("marked_lost", [])
    shown = tool_run_show(run_id, store_path=store)
    assert shown["run"]["state"] == "running"


def test_created_handoff_dead_launcher_is_unknown() -> None:
    import subprocess

    finished = subprocess.Popen(["true"])
    finished.wait()
    run = {
        "run_id": "handoff-1",
        "state": "created",
        "launch_mode": "handoff",
        "wrapper_pid": finished.pid,
        "boot_id": current_boot_id(),
        "process_start_identity": f"{current_boot_id()}:1",
    }
    fact = _observe_wrapper(run)
    assert fact["observation"] == "unknown"
    assert fact["reason"] == "launcher exit is not proof of launch failure"
    assert fact["run_id"] == "handoff-1"


def test_running_handoff_dead_wrapper_stays_dead() -> None:
    import subprocess

    finished = subprocess.Popen(["true"])
    finished.wait()
    run = {
        "run_id": "handoff-2",
        "state": "running",
        "launch_mode": "handoff",
        "wrapper_pid": finished.pid,
        "boot_id": current_boot_id(),
        "process_start_identity": f"{current_boot_id()}:1",
    }
    fact = _observe_wrapper(run)
    assert fact["observation"] == "dead"


def _created_handoff(launcher: dict[str, object] | None) -> dict[str, object]:
    return {
        "run_id": "handoff-launcher",
        "state": "created",
        "launch_mode": "handoff",
        "wrapper_pid": None,
        "launcher": launcher,
    }


def _dead_launcher() -> dict[str, object]:
    finished = subprocess.Popen(["true"])
    finished.wait()
    return {
        "pid": finished.pid,
        "boot_id": current_boot_id(),
        "process_start_identity": f"{current_boot_id()}:1",
    }


def test_dead_launcher_is_proof_only_when_the_owner_is_missing_or_terminal() -> None:
    run = _created_handoff(_dead_launcher())
    for state in ("missing", "terminal"):
        fact = _observe_launcher(run, {"kind": "proc", "id": "p", "state": state})
        assert fact["observation"] == "dead", state
        assert fact["wrapper_pid"] == run["launcher"]["pid"]  # type: ignore[index]
    for owner in (
        None,
        {"kind": "proc", "id": "p", "state": "active"},
        {"kind": "proc", "id": "p", "state": "unknown"},
    ):
        fact = _observe_launcher(run, owner)
        assert fact["observation"] == "unknown"
        assert fact["reason"] == "launcher exit is not proof of launch failure"


def test_alive_launcher_and_boot_mismatch_are_observed_truthfully() -> None:
    pid = os.getpid()
    alive = _created_handoff(
        {
            "pid": pid,
            "boot_id": current_boot_id(),
            "process_start_identity": process_identity_token(pid) or None,
        }
    )
    missing = {"kind": "proc", "id": "p", "state": "missing"}
    assert _observe_launcher(alive, missing)["observation"] == "alive"

    rebooted = _created_handoff(
        {
            "pid": pid,
            "boot_id": "another-boot",
            "process_start_identity": "another-boot:1",
        }
    )
    assert _observe_launcher(rebooted, missing)["observation"] == "dead"


def test_created_handoff_without_a_launcher_record_stays_unknown() -> None:
    fact = _observe_launcher(
        _created_handoff(None), {"kind": "proc", "id": "p", "state": "missing"}
    )
    assert fact["observation"] == "unknown"
    assert "not recorded" in str(fact["reason"])


def test_liveness_fact_attaches_owner_only_when_one_was_observed() -> None:
    owner = {"kind": "proc", "id": "p", "state": "missing"}
    running = {
        "run_id": "r",
        "state": "running",
        "launch_mode": "handoff",
        "wrapper_pid": os.getpid(),
        "boot_id": current_boot_id(),
        "process_start_identity": process_identity_token(os.getpid()) or None,
    }
    assert _liveness_fact(running, owner)["owner"] == owner
    assert "owner" not in _liveness_fact(running, None)
