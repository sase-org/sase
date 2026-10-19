"""Shared helpers for triage-input tests.

Public helpers for the ``test_triage_inputs*`` modules. Names are public so the
split modules can import them; the module itself is private (``_``-prefixed)
so no ``_``-prefixed name is ever imported across modules.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sase.config.core import clear_config_cache

NODE = "tests/test_foo.py::test_bar"
PYTEST_LINE = f"FAILED {NODE} - AssertionError\n"


def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    heim = tmp_path / "home"
    heim.mkdir()
    monkeypatch.setenv("SASE_HOME", str(heim))
    for name in (
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_PROC_ID",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_EVENTS",
        "SASE_TEST_SELECTION_HEALTH_DIR",
        "SASE_TEST_SELECTION_HEALTH_PROJECT_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return heim


def write_full_run(
    directory: Path,
    *,
    head: str,
    failures: list[str],
    recorded_at: datetime,
    workspace: str = "/tmp/sase_99",
    pid: int = 1,
    extra: dict[str, Any] | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = recorded_at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "schema": 2,
        "kind": "full-run",
        "recorded_at": recorded_at.astimezone(UTC).isoformat(),
        "head": head,
        "mode": "full",
        "exit_status": 1,
        "workspace": workspace,
        "changed_files": [],
        "tree_dirty": False,
        "failures": failures,
        **(extra or {}),
    }
    path = directory / f"{stamp}-{head[:12]}-{pid}-full-run.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
