"""Selection records flowing through settle, stage, and classify."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sase.core.tool_run import (
    tool_run_begin,
    tool_run_finish,
    tool_run_observe,
    tool_run_triage_classify,
    tool_run_triage_extract,
    tool_run_triage_settle,
    tool_run_triage_show,
    tool_run_triage_stage,
)
from sase.tool.triage_inputs import gather_selection_records
from sase.tool.triage_stage import _stage_decision
from tests.tool._triage_inputs_helpers import NODE, PYTEST_LINE, home, write_full_run

pytestmark = pytest.mark.skipif(
    not hasattr(importlib.import_module("sase_core_rs"), "tool_run_triage_settle"),
    reason="triage bindings are not in this wheel",
)


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
    home(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    now_ts = int(now.timestamp())
    head = "a" * 40
    selection_dir = tmp_path / "selection"
    write_full_run(
        selection_dir, head=head, failures=[NODE], recorded_at=now - timedelta(hours=1)
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
                    "output": PYTEST_LINE,
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
                "output": PYTEST_LINE,
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
    home(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    selection_dir = tmp_path / "selection"
    write_full_run(selection_dir, head="b" * 40, failures=[NODE], recorded_at=now)
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
            "output": PYTEST_LINE,
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
