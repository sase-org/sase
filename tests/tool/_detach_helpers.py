"""Shared setup helpers for detached tool-run tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.config.core import clear_config_cache
from sase.tool.executor import ToolRunCliRequest


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
        "SASE_TOOL_RUN_EVENTS",
        "SASE_TOOL_RUN_AGENT",
        "SASE_BEAD_ID",
        "SASE_BEAD",
        "SASE_WORKSPACE_NUM",
        "SASE_PROVIDER_SYNC_CEILING_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


def detach_request(
    *words: str,
    quiet: bool = False,
    verbose: bool = False,
    tail_lines_explicit: bool = False,
    keep_going: bool = False,
    fail_fast: bool = False,
    hand_off: bool = False,
) -> ToolRunCliRequest:
    return ToolRunCliRequest(
        quiet=quiet,
        verbose=verbose,
        tail_lines=200,
        words=tuple(words),
        hand_off=hand_off,
        detach=True,
        tail_lines_explicit=tail_lines_explicit,
        keep_going=keep_going,
        fail_fast=fail_fast,
    )


def agent_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    name: str = "agent-1",
    pid: int | None = None,
) -> Path:
    """Agent env whose runner PID is live (defaults to this test process)."""

    from sase.core.process_identity import process_identity_token

    runner_pid = pid if pid is not None else os.getpid()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": runner_pid,
                "process_identity": process_identity_token(runner_pid),
                "name": name,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", name)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    return artifacts
