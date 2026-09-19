from __future__ import annotations

import os
from pathlib import Path
import subprocess

from sase.core.process_identity import process_identity_token
from sase.core.tool_run import tool_run_begin, tool_run_show
from sase.tool.liveness import (
    current_boot_id,
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
