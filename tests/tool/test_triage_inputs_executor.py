"""Executor diagnostics and stage execution for triage inputs."""

from __future__ import annotations

import importlib
import json
import sqlite3
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from sase.core.tool_run import (
    tool_run_begin,
    tool_run_list,
    tool_run_observe,
    tool_run_store_path,
    tool_run_triage_show,
)
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.triage_stage import execute_triage_stage
from tests.tool._triage_inputs_helpers import NODE, PYTEST_LINE, home, write_full_run

pytestmark = pytest.mark.skipif(
    not hasattr(importlib.import_module("sase_core_rs"), "tool_run_triage_settle"),
    reason="triage bindings are not in this wheel",
)


def _project(tmp_path: Path, script: str) -> Path:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    sase_dir = root / "sase"
    sase_dir.mkdir()
    catalog = {
        "tools": {
            "check": {
                "argv": ["bash", "-lc", script],
                "description": "fixture",
                "stages": "run_silent",
                "inputs": [],
                "env": [],
                "args": "deny",
                "fingerprint": {"repos": [], "toolchain": {}},
            }
        }
    }
    (sase_dir / "sase.yml").write_text(yaml.safe_dump(catalog), encoding="utf-8")
    return root


def _run() -> int:
    return execute_tool_run(
        ToolRunCliRequest(quiet=False, verbose=False, tail_lines=200, words=("check",))
    )


def test_gatherer_timeout_stores_diagnostic_and_keeps_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home(monkeypatch, tmp_path)
    root = _project(tmp_path, "sh -c 'echo boom; exit 9'")
    monkeypatch.chdir(root)

    def _slow(_root: Path, *, now_ts: int | None = None) -> tuple[list[Any], list[str]]:
        del now_ts
        time.sleep(1.5)  # sase-test-wait: exceed 1.0s owner-candidate gatherer slice
        return [], []

    monkeypatch.setattr("sase.tool.executor_triage.gather_owner_candidates", _slow)
    assert _run() == 9
    run_id = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]["run_id"]
    shown = tool_run_triage_show({"run_id": run_id})
    diagnostics = list(shown.get("diagnostics") or [])
    facts = shown.get("run_facts") or {}
    diagnostics.extend(facts.get("diagnostics") or [])
    assert any("timed out" in str(note) for note in diagnostics), shown


def test_settle_exception_stores_diagnostic_and_keeps_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home(monkeypatch, tmp_path)
    root = _project(tmp_path, "sh -c 'echo boom; exit 6'")
    monkeypatch.chdir(root)

    def _boom(*_args: object, **_kwargs: object) -> dict[str, Any]:
        raise RuntimeError("forced settle failure")

    monkeypatch.setattr("sase.tool.executor_triage.tool_run_triage_settle", _boom)
    assert _run() == 6
    run_id = tool_run_list({"schema_version": 1, "limit": 1})["runs"][0]["run_id"]
    shown = tool_run_triage_show({"run_id": run_id})
    diagnostics = list(shown.get("diagnostics") or [])
    facts = shown.get("run_facts") or {}
    diagnostics.extend(facts.get("diagnostics") or [])
    assert any("forced settle failure" in str(note) for note in diagnostics), shown


def test_execute_triage_stage_continues_for_selection_witness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home(monkeypatch, tmp_path)
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Fixture"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    (root / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "fixture"], cwd=root, check=True, capture_output=True
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    now = datetime.now(UTC)
    selection_dir = tmp_path / "selection"
    write_full_run(selection_dir, head=head, failures=[NODE], recorded_at=now)
    monkeypatch.setenv("SASE_TEST_SELECTION_HEALTH_DIR", str(selection_dir))
    monkeypatch.chdir(root)

    now_ts = int(now.timestamp())
    begun = tool_run_begin(
        {
            "schema_version": 1,
            "tool_name": "check",
            "definition": {
                "schema_version": 1,
                "name": "check",
                "argv": ["true"],
                "description": "fixture",
                "stages": "run_silent",
                "inputs": [],
                "env": [],
                "args": "deny",
                "fingerprint": {"repos": [], "toolchain": {}},
            },
            "display_argv": ["true"],
            "project": "fixture",
            "workspace": "stage-workspace",
            "now_ts": now_ts,
            "commit_running": True,
        }
    )["run"]
    run_id = str(begun["run_id"])
    extra_digest = str(begun.get("extra_args_digest") or "")
    tool_run_observe(
        {
            "schema_version": 1,
            "run_id": run_id,
            "fingerprint_before": {
                "schema_version": 1,
                "project_identity": "fixture",
                "extra_args_digest": extra_digest,
                "repos": [{"identity": "fixture", "head": head, "dirty_paths": []}],
                "completeness": {"complete": True},
            },
        }
    )
    output = tmp_path / "stage.log"
    output.write_text(PYTEST_LINE, encoding="utf-8")
    code = execute_triage_stage(
        run_id,
        stage_id="stage-1",
        description="test (scoped)",
        output=str(output),
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["decision"] == "continue"
    assert payload["reason"] == "all_known_or_flaky"
    assert code == 0


def test_execute_triage_stage_waits_for_tool_store_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A transient store writer must not turn a generic result into helper_error."""
    home(monkeypatch, tmp_path)
    begun = tool_run_begin(
        {
            "schema_version": 1,
            "tool_name": "check",
            "definition": {
                "schema_version": 1,
                "name": "check",
                "argv": ["true"],
                "description": "fixture",
                "stages": "run_silent",
                "inputs": [],
                "env": [],
                "args": "deny",
                "fingerprint": {"repos": [], "toolchain": {}},
            },
            "display_argv": ["true"],
            "project": "fixture",
            "workspace": "stage-workspace",
            "commit_running": True,
        }
    )["run"]
    run_id = str(begun["run_id"])
    tool_run_observe(
        {
            "schema_version": 1,
            "run_id": run_id,
            "fingerprint_before": {
                "schema_version": 1,
                "project_identity": "fixture",
                "extra_args_digest": str(begun.get("extra_args_digest") or ""),
                "repos": [
                    {"identity": "fixture", "head": "deadbeef", "dirty_paths": []}
                ],
                "completeness": {"complete": True},
            },
        }
    )
    output = tmp_path / "stage.log"
    output.write_text("plain boom with no shape\n", encoding="utf-8")

    store_lock = sqlite3.connect(tool_run_store_path(), check_same_thread=False)
    store_lock.execute("BEGIN IMMEDIATE")

    def _release_store_lock() -> None:
        time.sleep(0.6)  # sase-test-wait: let the SQLite retry block.
        store_lock.rollback()
        store_lock.close()

    releaser = threading.Thread(target=_release_store_lock)
    releaser.start()
    try:
        code = execute_triage_stage(
            run_id,
            stage_id="stage-1",
            description="opaque",
            output=str(output),
        )
    finally:
        releaser.join(timeout=5)

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["decision"] == "stop"
    assert payload["reason"] == "unknown_item", captured.err
    assert code == 1
