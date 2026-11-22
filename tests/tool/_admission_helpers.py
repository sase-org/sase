"""Shared public fixtures for the admission test modules."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.core import tool_run as core
from sase.core.tool_run import tool_run_admission_enter, tool_run_begin, tool_run_show
from sase.tool import admission as gate
from sase.tool.argv import resolve_run_argv
from sase.tool.executor_models import RecordedRunContext
from sase.tool.executor_recording import build_begin_request, finish_tool_run
from sase.tool.executor_signals import SignalState


def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_ARTIFACTS_DIR",
        "SASE_MONITOR_ID",
        "SASE_MONITOR_ARTIFACTS_DIR",
        "SASE_PROC_ID",
        "SASE_PROC_LOG_PATH",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_AGENT_CHILD",
        "SASE_TOOL_RUN_EVENTS",
        "SASE_TOOL_RUN_AGENT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    # Fast loop for in-process tests; the subprocess tests use real cadence.
    monkeypatch.setattr(gate, "POLL_SECONDS", 0.05)
    monkeypatch.setattr(gate, "POLL_JITTER_SECONDS", 0.0)
    monkeypatch.setattr(gate, "SLICE_SECONDS", 0.01)
    monkeypatch.setattr(gate, "SWEEP_SECONDS", 0.2)
    return home


def project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    admission: object = None,
    script: str = "true",
) -> Path:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True, exist_ok=True)
    (root / "sase").mkdir(exist_ok=True)
    config: dict[str, Any] = {
        "tools": {
            "check": {
                "argv": ["sh", "-c", script],
                "description": "admission fixture",
                "args": "deny",
                "inputs": [],
                "env": [],
                "fingerprint": {"repos": [], "toolchain": {}},
            }
        }
    }
    if admission is not None:
        config["tool_runs"] = {"admission": admission}
    (root / "sase" / "sase.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.chdir(root)
    clear_config_cache()
    return root


def begin(words: tuple[str, ...] = ("check",), **overrides: Any) -> tuple[str, Any]:
    run_id = secrets.token_hex(16)
    resolved = resolve_run_argv(list(words))
    request = build_begin_request(
        run_id,
        resolved=resolved,
        owner_kind=None,
        owner_id=None,
        parent_run_id=None,
        events_path=None,
        stdout_path=None,
        stderr_path=None,
    )
    request.update(overrides)
    started = tool_run_begin(request)
    assert started["run"]["state"] == "running"
    return run_id, resolved


def ctx(run_id: str, resolved: Any, **fields: Any) -> RecordedRunContext:
    values: dict[str, Any] = {
        "run_id": run_id,
        "recorded": True,
        "resolved": resolved,
        "has_owner": False,
        "owns_output": True,
        "compact": False,
        "tail_lines": 200,
        "events_path": None,
        "stdout_path": None,
        "stderr_path": None,
    }
    values.update(fields)
    return RecordedRunContext(**values)


def hold_slot(limit: int = 1, **overrides: Any) -> str:
    """Record a running ``check`` run that holds one slot."""

    holder, _ = begin(**overrides)
    entered = tool_run_admission_enter(
        {"schema_version": 1, "run_id": holder, "key": "check", "limit": limit}
    )
    assert entered["outcome"] == "admitted"
    return holder


def record_for_run(run_id: str) -> dict[str, Any]:
    run = tool_run_show(run_id)["run"]
    demand = run.get("demand") or {}
    record = demand.get("admission")
    assert isinstance(record, dict), f"run {run_id} has no admission record"
    return record


def settle_run(run_id: str) -> None:
    assert finish_tool_run(
        run_id, state="succeeded", exit_code=0, duration_ms=1, terminal_cause="exited"
    )


def admit(ctx: RecordedRunContext) -> Any:
    return gate.admit_before_spawn(ctx, SignalState(), show_header=lambda: None)
