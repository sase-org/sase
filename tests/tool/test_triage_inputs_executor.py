"""Executor diagnostics and stage execution for triage inputs."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
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

    # The bundled Rust SQLite and stdlib SQLite must never open this ledger
    # in the same process: POSIX locks cannot arbitrate between those copies.
    holder_script = """
import sqlite3, sys, time
with sqlite3.connect(sys.argv[1]) as connection:
    connection.execute("BEGIN IMMEDIATE")
    print("locked", flush=True)
    sys.stdin.readline()
    time.sleep(0.6)  # sase-test-wait: exceed the core default, within the stage budget.
    connection.rollback()
"""
    with subprocess.Popen(
        [sys.executable, "-c", holder_script, str(tool_run_store_path())],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as holder:
        try:
            assert holder.stdout is not None and holder.stdin is not None
            assert holder.stdout.readline().strip() == "locked"
            holder.stdin.write("release after delay\n")
            holder.stdin.flush()
            code = execute_triage_stage(
                run_id,
                stage_id="stage-1",
                description="opaque",
                output=str(output),
            )
            assert holder.wait(timeout=5) == 0
        finally:
            if holder.poll() is None:
                holder.kill()
            holder.wait()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["decision"] == "stop"
    assert payload["reason"] == "unknown_item", captured.err
    assert code == 1


def test_stage_triage_retains_explicit_store_allowance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.tool import triage_stage

    home(monkeypatch, tmp_path)
    show = Mock(return_value={"run": {"run_id": "run-1"}})
    settle = Mock(return_value={"items": [{"label": {"class": "known"}}]})
    monkeypatch.setattr(triage_stage, "tool_run_show", show)
    monkeypatch.setattr(triage_stage, "tool_run_triage_stage", settle)
    monkeypatch.setattr(
        triage_stage, "_gather_stage_inputs", lambda *_args: ([], [], [])
    )

    assert (
        execute_triage_stage(
            "run-1", stage_id="stage-1", description="lint", output=None
        )
        == 0
    )
    assert show.call_args.kwargs["busy_timeout_ms"] == 2_000
    assert settle.call_args.kwargs["busy_timeout_ms"] == 2_000


def test_executor_triage_passes_remaining_deadline_to_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.tool import executor_triage

    now = [100.0]
    monkeypatch.setattr(
        executor_triage,
        "time",
        SimpleNamespace(monotonic=lambda: now[0], time=lambda: 10),
    )
    monkeypatch.setattr(executor_triage, "_failed_stage_inputs", lambda *_args: [])

    def gather(*_args: object) -> tuple[list[Any], list[str]]:
        now[0] += 0.5
        return [], []

    def settle(_request: object, *, busy_timeout_ms: int) -> dict[str, Any]:
        assert busy_timeout_ms == 3_000
        now[0] += 0.125
        return {"triaged": True}

    monkeypatch.setattr(executor_triage, "_gather_triage", gather)
    settle_call = Mock(side_effect=settle)
    show = Mock(return_value={})
    monkeypatch.setattr(executor_triage, "tool_run_triage_settle", settle_call)
    monkeypatch.setattr(executor_triage, "tool_run_triage_show", show)
    ctx = SimpleNamespace(
        run_id="run-1",
        events_path=tmp_path / "events.jsonl",
        continuation_mode="never",
        resolved=SimpleNamespace(
            adhoc=False,
            tool_name="check",
            cwd=str(tmp_path),
            resolved_project_identity=lambda: "fixture",
        ),
    )
    executor_triage.settle_failure_triage(
        ctx=ctx,
        fingerprint_before={"repos": [{"head": "base"}]},
        ingestor=None,
        state="succeeded",
    )
    settle_call.assert_called_once()
    show.assert_called_once_with({"run_id": "run-1"}, busy_timeout_ms=2_875)
