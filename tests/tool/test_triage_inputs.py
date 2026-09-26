"""Wire-valid selection evidence and stored triage diagnostics."""

from __future__ import annotations

import importlib
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.core.tool_run import (
    tool_run_begin,
    tool_run_finish,
    tool_run_list,
    tool_run_observe,
    tool_run_triage_classify,
    tool_run_triage_extract,
    tool_run_triage_settle,
    tool_run_triage_show,
    tool_run_triage_stage,
)
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.triage_inputs import gather_selection_records
from sase.tool.triage_stage import _stage_decision, execute_triage_stage


pytestmark = pytest.mark.skipif(
    not hasattr(importlib.import_module("sase_core_rs"), "tool_run_triage_settle"),
    reason="triage bindings are not in this wheel",
)

_NODE = "tests/test_foo.py::test_bar"
_PYTEST_LINE = f"FAILED {_NODE} - AssertionError\n"


def _home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
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
    return home


def _write_full_run(
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


def test_gather_selection_records_emits_wire_valid_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _home(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    selection_dir = tmp_path / "selection"
    _write_full_run(
        selection_dir,
        head="abc123def456",
        failures=[_NODE],
        recorded_at=now,
    )
    records, diagnostics = gather_selection_records(
        "fixture",
        now_ts=int(now.timestamp()),
        project="fixture",
        tool="check",
        extra_args_digest="",
        selection_dir=selection_dir,
        project_root=tmp_path,
    )
    assert diagnostics == []
    assert len(records) == 1
    record = records[0]
    assert "failures" not in record
    assert record["selection_source"] is True
    assert record["items"]
    item = record["items"][0]
    assert set(item) <= {"extractor", "extractor_version", "signature", "stage_key"}
    assert item["extractor"] == "pytest"
    assert item["stage_key"] == "test (scoped)"
    expected = tool_run_triage_extract(
        {
            "stage_key": "test (scoped)",
            "output": f"FAILED {_NODE}",
            "project_root": str(tmp_path),
        }
    )["items"][0]
    assert item["signature"] == expected["signature"]


def test_gather_selection_records_skips_old_mtime_before_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _home(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    selection_dir = tmp_path / "selection"
    stale = _write_full_run(
        selection_dir,
        head="deadbeef0001",
        failures=[_NODE],
        recorded_at=now,
        pid=1,
    )
    fresh = _write_full_run(
        selection_dir,
        head="deadbeef0002",
        failures=["tests/test_fresh.py::test_ok"],
        recorded_at=now,
        pid=2,
    )
    old = time.time() - 8 * 86400
    os.utime(stale, (old, old))
    records, _diagnostics = gather_selection_records(
        "fixture",
        now_ts=int(now.timestamp()),
        selection_dir=selection_dir,
        project_root=tmp_path,
    )
    assert [row["base_head"] for row in records] == ["deadbeef0002"]
    assert fresh.exists()


def test_gather_selection_records_empty_failures_are_empty_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _home(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    selection_dir = tmp_path / "selection"
    _write_full_run(selection_dir, head="abc123", failures=[], recorded_at=now)
    records, diagnostics = gather_selection_records(
        "fixture",
        now_ts=int(now.timestamp()),
        selection_dir=selection_dir,
        project_root=tmp_path,
    )
    assert diagnostics == []
    assert records[0]["items"] == []
    assert "failures" not in records[0]


def test_gather_selection_records_extraction_error_drops_items(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _home(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    selection_dir = tmp_path / "selection"
    _write_full_run(selection_dir, head="abc123", failures=[_NODE], recorded_at=now)

    def _boom(_request: object) -> dict[str, Any]:
        raise RuntimeError("extract boom")

    monkeypatch.setattr("sase.tool.triage_inputs.tool_run_triage_extract", _boom)
    records, diagnostics = gather_selection_records(
        "fixture",
        now_ts=int(now.timestamp()),
        selection_dir=selection_dir,
        project_root=tmp_path,
    )
    assert records[0]["items"] == []
    assert any("extract boom" in note for note in diagnostics)


def _seed_named_run(
    tmp_path: Path, *, head: str, now_ts: int, project: str = "fixture"
) -> tuple[str, str]:
    definition = {
        "schema_version": 1,
        "name": "check",
        "argv": ["true"],
        "description": "fixture",
        "stages": "run_silent",
        "inputs": [],
        "env": [],
        "args": "deny",
        "fingerprint": {"repos": [], "toolchain": {}},
    }
    begun = tool_run_begin(
        {
            "schema_version": 1,
            "tool_name": "check",
            "definition": definition,
            "display_argv": ["true"],
            "project": project,
            "workspace": "subject-workspace",
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
                "project_identity": project,
                "repos": [{"identity": project, "head": head, "dirty_paths": []}],
                "completeness": {"complete": True},
            },
        }
    )
    tool_run_finish(
        {
            "schema_version": 1,
            "run_id": run_id,
            "state": "failed",
            "exit_code": 5,
            "duration_ms": 1,
            "now_ts": now_ts + 1,
        }
    )
    return run_id, extra_digest


def test_selection_record_flows_through_settle_and_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _home(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    now_ts = int(now.timestamp())
    head = "a" * 40
    selection_dir = tmp_path / "selection"
    _write_full_run(
        selection_dir, head=head, failures=[_NODE], recorded_at=now - timedelta(hours=1)
    )
    run_id, extra_digest = _seed_named_run(tmp_path, head=head, now_ts=now_ts)
    records, diagnostics = gather_selection_records(
        "fixture",
        now_ts=now_ts,
        project="fixture",
        tool="check",
        extra_args_digest=extra_digest,
        selection_dir=selection_dir,
        project_root=tmp_path,
    )
    assert diagnostics == []
    assert records and records[0]["items"]
    settled = tool_run_triage_settle(
        {
            "run_id": run_id,
            "stages": [
                {
                    "stage_key": "test (scoped)",
                    "stage_id": "stage-1",
                    "output": _PYTEST_LINE,
                    "truncated": False,
                    "output_path": "logs/stage.log",
                }
            ],
            "project_root": str(tmp_path),
            "workspace_roots": [str(tmp_path)],
            "ancestry": [head],
            "flake_baseline": [],
            "selection_records": records,
            "owner_candidates": [],
            "knobs": {"min_witnesses": 1, "touched_requires_clean_witness": False},
            "continuation_mode": "known",
            "now_ts": now_ts + 2,
        }
    )
    assert not settled.get("refused"), settled
    shown = tool_run_triage_show({"run_id": run_id})
    assert shown["triaged"] is True, shown.get("diagnostics")
    items = [item for item in shown["items"] if item["stage_key"] == "test (scoped)"]
    assert items
    assert all(item["label"]["class"] == "known" for item in items)

    running = tool_run_begin(
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
            "now_ts": now_ts + 10,
            "commit_running": True,
        }
    )["run"]["run_id"]
    tool_run_observe(
        {
            "schema_version": 1,
            "run_id": running,
            "fingerprint_before": {
                "schema_version": 1,
                "project_identity": "fixture",
                "repos": [{"identity": "fixture", "head": head, "dirty_paths": []}],
                "completeness": {"complete": True},
            },
        }
    )
    known_stage = tool_run_triage_stage(
        {
            "run_id": running,
            "stage": {
                "stage_key": "test (scoped)",
                "stage_id": "stage-known",
                "output": _PYTEST_LINE,
                "truncated": False,
            },
            "project_root": str(tmp_path),
            "workspace_roots": [str(tmp_path)],
            "ancestry": [head],
            "flake_baseline": [],
            "selection_records": records,
            "owner_candidates": [],
            "knobs": {"min_witnesses": 1, "touched_requires_clean_witness": False},
            "now_ts": now_ts + 11,
        }
    )
    assert not known_stage.get("refused"), known_stage
    decision, reason, _counts = _stage_decision(known_stage.get("items"))
    assert (decision, reason) == ("continue", "all_known_or_flaky")

    new_run = tool_run_begin(
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
            "workspace": "new-workspace",
            "now_ts": now_ts + 20,
            "commit_running": True,
        }
    )["run"]["run_id"]
    tool_run_observe(
        {
            "schema_version": 1,
            "run_id": new_run,
            "fingerprint_before": {
                "schema_version": 1,
                "project_identity": "fixture",
                "extra_args_digest": extra_digest,
                "repos": [{"identity": "fixture", "head": head, "dirty_paths": []}],
                "completeness": {"complete": True},
            },
        }
    )
    new_stage = tool_run_triage_stage(
        {
            "run_id": new_run,
            "stage": {
                "stage_key": "test (scoped)",
                "stage_id": "stage-new",
                "output": "FAILED tests/test_unseen.py::test_new - boom\n",
                "truncated": False,
            },
            "project_root": str(tmp_path),
            "workspace_roots": [str(tmp_path)],
            "ancestry": [head],
            "flake_baseline": [],
            "selection_records": records,
            "owner_candidates": [],
            "knobs": {"min_witnesses": 1, "touched_requires_clean_witness": False},
            "now_ts": now_ts + 21,
        }
    )
    decision, reason, _counts = _stage_decision(new_stage.get("items"))
    assert decision == "stop"
    assert reason in {"new_item", "unknown_item"}


def test_classify_accepts_gathered_selection_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _home(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    selection_dir = tmp_path / "selection"
    _write_full_run(selection_dir, head="b" * 40, failures=[_NODE], recorded_at=now)
    records, diagnostics = gather_selection_records(
        "fixture",
        now_ts=int(now.timestamp()),
        project="fixture",
        selection_dir=selection_dir,
        project_root=tmp_path,
    )
    assert diagnostics == []
    extracted = tool_run_triage_extract(
        {
            "stage_key": "test (scoped)",
            "output": _PYTEST_LINE,
            "project_root": str(tmp_path),
        }
    )["items"][0]
    result = tool_run_triage_classify(
        {
            "subject_run": {
                "run_id": "subject",
                "project": "fixture",
                "tool": "check",
                "extra_args_digest": "",
                "workspace": "subject-workspace",
                "base_head": "b" * 40,
                "dirty_paths": [],
                "complete_fingerprint": True,
                "fingerprint_digest": "subject-fingerprint",
                "ad_hoc": False,
            },
            "subjects": [
                {
                    "stage_key": extracted["stage_key"],
                    "extractor": extracted["extractor"],
                    "extractor_version": extracted["extractor_version"],
                    "signature": extracted["signature"],
                    "locator_paths": extracted.get("locator_paths") or [],
                }
            ],
            "evidence_runs": [],
            "selection_records": records,
            "ancestry": ["b" * 40],
            "flake_baseline": [],
            "owner_candidates": [],
            "knobs": {"min_witnesses": 1, "touched_requires_clean_witness": False},
            "now_ts": int(now.timestamp()),
        }
    )
    assert result["labels"][0]["class"] == "known"


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
    _home(monkeypatch, tmp_path)
    root = _project(tmp_path, "sh -c 'echo boom; exit 9'")
    monkeypatch.chdir(root)

    def _slow(_root: Path, *, now_ts: int | None = None) -> tuple[list[Any], list[str]]:
        del now_ts
        time.sleep(1.5)  # sase-test-wait: exceed 1.0s owner-candidate gatherer slice
        return [], []

    monkeypatch.setattr("sase.tool.executor.gather_owner_candidates", _slow)
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
    _home(monkeypatch, tmp_path)
    root = _project(tmp_path, "sh -c 'echo boom; exit 6'")
    monkeypatch.chdir(root)

    def _boom(*_args: object, **_kwargs: object) -> dict[str, Any]:
        raise RuntimeError("forced settle failure")

    monkeypatch.setattr("sase.tool.executor.tool_run_triage_settle", _boom)
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
    import subprocess

    _home(monkeypatch, tmp_path)
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
    _write_full_run(selection_dir, head=head, failures=[_NODE], recorded_at=now)
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
    output.write_text(_PYTEST_LINE, encoding="utf-8")
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
