"""Typed ``tool.stop`` results for durable-proc submissions (sase-1bt.11)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sase.config.core import clear_config_cache
from sase.core.tool_run import tool_run_begin, tool_run_finish
from sase.ops import RESULT_ENV, read_operation_result
from sase.tool.control import ToolStopCliRequest, handle_stop


def _clean_env(monkeypatch: Any, tmp_path: Path) -> Path:
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


def _seed_definition() -> dict:
    return {
        "schema_version": 1,
        "name": "seeded",
        "argv": ["true"],
        "description": "",
        "stages": "none",
        "inputs": [],
        "env": [],
        "args": "allow",
        "fingerprint": {"repos": [], "toolchain": {}},
    }


def _begin(state: str = "running", **overrides: Any) -> str:
    request: dict[str, Any] = {
        "schema_version": 1,
        "definition": _seed_definition(),
        "display_argv": ["true"],
        "project": "fixture",
        "commit_running": True,
    }
    request.update(overrides)
    if state == "running":
        request.setdefault("wrapper_pid", os.getpid())
    return tool_run_begin(request)["run"]["run_id"]


def _arm_result(monkeypatch: Any, tmp_path: Path, name: str = "result.json") -> Path:
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROC_ID", "proc-stop-test")
    path = tmp_path / name
    monkeypatch.setenv(RESULT_ENV, str(path))
    return path


def test_unknown_run_writes_typed_failure(tmp_path: Path, monkeypatch: Any) -> None:
    """An unknown run id exits 2 and still writes a typed failure result."""

    path = _arm_result(monkeypatch, tmp_path)
    code = handle_stop(ToolStopCliRequest(run_id="0" * 32))
    assert code == 2
    loaded = read_operation_result(
        path, expected_operation="tool.stop", expected_proc_id="proc-stop-test"
    )
    assert loaded.success is False
    assert loaded.payload["run_id"] == "0" * 32
    assert loaded.payload["outcome"] == "not_found"


def test_already_settled_run_writes_typed_success(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A settled run exits 0 with a typed success so the proc completes."""

    path = _arm_result(monkeypatch, tmp_path)
    run_id = _begin(state="created")
    tool_run_finish(
        {
            "schema_version": 1,
            "run_id": run_id,
            "state": "succeeded",
            "exit_code": 0,
            "duration_ms": 5,
        }
    )
    code = handle_stop(ToolStopCliRequest(run_id=run_id, json=True))
    assert code == 0
    loaded = read_operation_result(
        path, expected_operation="tool.stop", expected_proc_id="proc-stop-test"
    )
    assert loaded.success is True
    assert loaded.payload["run_id"] == run_id
    assert str(loaded.payload["outcome"]).startswith("already")
    assert loaded.payload["state"] == "succeeded"


def test_nested_refusal_writes_typed_failure(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    """A nested foreground run is refused (exit 2) with a typed failure."""

    path = _arm_result(monkeypatch, tmp_path)
    parent = _begin(state="created")
    child = _begin(state="created", parent_run_id=parent)
    code = handle_stop(ToolStopCliRequest(run_id=child))
    assert code == 2
    assert f"sase tool stop {parent}" in capsys.readouterr().err
    loaded = read_operation_result(
        path, expected_operation="tool.stop", expected_proc_id="proc-stop-test"
    )
    assert loaded.success is False
    assert loaded.payload["run_id"] == child
    assert loaded.payload["outcome"] == "owner_stop_failed"
