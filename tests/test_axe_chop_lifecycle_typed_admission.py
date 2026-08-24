"""Typed-admission chop action lifecycle coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.agent.launch_admission_store import RECEIPT_FILENAME, admission_dir
from sase.agent.launch_request_types import DIRECT_TYPED_LAUNCH_KIND
from sase.axe.chop_agents import get_chop_agent_records
from sase.axe.chop_lifecycle import finalize_launched_chop_runs
from sase.axe.chop_policy import apply_chop_once_per
from sase.axe.chop_proposals import prepare_chop_proposals
from sase.axe.config import ChopConfig
from sase.axe.state import chop_run_log_path, read_chop_run
from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path
from sase.notification_gates.paths import REQUEST_FILENAME

from tests._axe_chop_lifecycle_helpers import launched_entry, record_agent

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def _typed_bundle(
    tmp_path: Path,
    *,
    logical_id: str,
    outcome: str,
    dedupe_key: str = "",
) -> tuple[Path, dict[str, object]]:
    bundle = tmp_path / f"bundle-{logical_id}"
    metadata = {
        logical_id: {
            "lumberjack_name": "docs",
            "chop_name": "docs",
            "run_id": "run-typed",
            "logical_id": logical_id,
            "source_order": 0,
            "proposal_index": 0,
            "proposal_id": "refresh",
            "agent_name": "refresh",
            "clan": "toobig-0",
            "member_id": "refresh",
            "workspace": "git:sase",
            "dedupe_key": dedupe_key,
            "wait_on": None,
            "wait_name": None,
            "env": {},
        }
    }
    payload: dict[str, object] = {
        "request_id": f"req-{logical_id}",
        "source_surface": "axe_chop",
        "plan_digest": "digest",
        "typed_plan": {
            "schema_version": 1,
            "launch_kind": "axe_chop",
            "selected_project": "sase",
            "content_digest": "digest",
            "units": [],
            "approval_preview": [],
            "diagnostics": [],
        },
        "unit_dispatch_metadata": metadata,
        "dispatch": {"cwd": str(tmp_path), "prompt": "prompt"},
    }
    bundle.mkdir(parents=True)
    (bundle / REQUEST_FILENAME).write_text(
        json.dumps(
            {
                "kind": DIRECT_TYPED_LAUNCH_KIND,
                "request_id": f"req-{logical_id}",
                "payload": payload,
            }
        ),
        encoding="utf-8",
    )
    root = admission_dir(bundle)
    root.mkdir(parents=True)
    (root / RECEIPT_FILENAME).write_text(
        json.dumps(
            {
                "complete": True,
                "summary": {
                    "total": 1,
                    "eligible": 1 if outcome == "launched" else 0,
                    "launched": 1 if outcome == "launched" else 0,
                    "skipped": 1 if outcome == "skipped" else 0,
                    "condition_errors": 1 if outcome == "condition_error" else 0,
                    "launch_errors": 1 if outcome == "launch_error" else 0,
                },
                "units": [{"logical_id": logical_id, "outcome": outcome}],
            }
        ),
        encoding="utf-8",
    )
    typed_admission = {
        "request_id": f"req-{logical_id}",
        "bundle_dir": str(bundle),
        "plan_digest": "digest",
        "source_surface": "axe_chop",
        "units": [
            {
                "logical_id": logical_id,
                "source_order": 0,
                "proposal_index": 0,
                "proposal_id": "refresh",
                "dedupe_key": dedupe_key,
            }
        ],
    }
    return bundle, typed_admission


def test_lifecycle_reconstructs_typed_admission_launch_from_registry(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120020_000000"
    _bundle, typed_admission = _typed_bundle(
        tmp_path,
        logical_id="unit-1",
        outcome="launched",
        dedupe_key="docs:refresh",
    )
    launched_entry(
        run_id,
        pid=0,
        launches=[],
        typed_admission=typed_admission,
    )
    record_agent(
        run_id,
        pid=777,
        admission_logical_id="unit-1",
        admission_fingerprint="fp-1",
        proposal_index=0,
        proposal_id="refresh",
    )
    artifacts = resolve_agent_artifact_timestamp_path(
        "sase", "ace-run", "20260718120000"
    )
    artifacts.mkdir(parents=True)
    (artifacts / "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )

    assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"
    output = chop_run_log_path("docs", "docs", run_id).read_text(encoding="utf-8")
    assert "typed admission completed: 1 launched, 0 skipped" in output
    assert get_chop_agent_records("docs", chop_name="docs", run_id=run_id) == []


def test_lifecycle_releases_once_per_key_for_skipped_typed_unit(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120021_000000"
    chop = ChopConfig(name="docs", description="")
    proposed = prepare_chop_proposals(
        "docs",
        {
            "proposed_launches": [
                {
                    "prompt": "Refresh.",
                    "workspace": "git:sase",
                    "dedupe_key": "docs:skip",
                }
            ]
        },
    )
    seeded = apply_chop_once_per(
        lumberjack_name="docs",
        chop=chop,
        proposals=proposed,
        persist=True,
    )
    assert seeded.accepted_indices == (0,)
    _bundle, typed_admission = _typed_bundle(
        tmp_path,
        logical_id="unit-skip",
        outcome="skipped",
        dedupe_key="docs:skip",
    )
    launched_entry(
        run_id,
        pid=0,
        launches=[],
        typed_admission=typed_admission,
    )

    assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"
    retried = apply_chop_once_per(
        lumberjack_name="docs",
        chop=chop,
        proposals=proposed,
        persist=False,
    )
    assert retried.accepted_indices == (0,)
    output = chop_run_log_path("docs", "docs", run_id).read_text(encoding="utf-8")
    assert "Released 1 once-per key(s) after typed admission" in output
