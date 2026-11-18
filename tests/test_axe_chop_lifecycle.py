"""Completion, dismissed-bundle, and duration chop lifecycle coverage."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe._chop_lifecycle_completion import agent_completion
from sase.axe._chop_lifecycle_keys import (
    release_failed_launch_keys,
    release_typed_nonlaunched_keys,
)
from sase.axe._chop_lifecycle_types import AgentCompletion, MatchedAgentRecord
from sase.axe import chop_batch_store
from sase.axe.chop_agents import get_chop_agent_records
from sase.axe.chop_lifecycle import finalize_launched_chop_runs
from sase.axe.state import read_chop_run
from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path
from sase.core.axe_chop_facade import CHOP_BATCH_SCHEMA_VERSION

from tests._axe_chop_lifecycle_helpers import launched_entry, record_agent

pytest_plugins = ["tests.axe_chop_runner_fixtures"]


def test_lifecycle_finalizes_completed_agents_and_clears_registry(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120000_000000"
    launched_entry(run_id, pid=321)
    record_agent(run_id, pid=321)
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
    assert get_chop_agent_records("docs", chop_name="docs", run_id=run_id) == []


def test_lifecycle_waits_for_open_batch_with_pending_dispatch(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120000_000002"
    launched_entry(run_id, pid=322)
    record_agent(run_id, pid=322)
    chop_batch_store.create_chop_batch(
        "docs",
        "docs",
        {
            "schema_version": CHOP_BATCH_SCHEMA_VERSION,
            "batch_id": run_id,
            "run": {"routine": "docs", "job": "docs", "run_id": run_id},
            "members": [
                {
                    "source_index": 0,
                    "proposal_id": "refresh",
                    "agent_name": "refresh",
                    "prompt": "Review the docs.",
                    "workspace": "git:sase",
                }
            ],
        },
    )

    assert finalize_launched_chop_runs("docs", ["docs"]) == 0
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "launched"


def test_lifecycle_releases_only_terminal_nonlaunch_batch_claims(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120000_000003"
    manifest = {
        "schema_version": CHOP_BATCH_SCHEMA_VERSION,
        "batch_id": run_id,
        "run": {"routine": "docs", "job": "docs", "run_id": run_id},
        "members": [
            {
                "source_index": index,
                "proposal_id": f"proposal-{index}",
                "agent_name": f"refresh-{index}",
                "prompt": "Review the docs.",
                "workspace": "git:sase",
            }
            for index in range(2)
        ],
    }
    chop_batch_store.create_chop_batch("docs", "docs", manifest)
    chop_batch_store.apply_chop_batch_event(
        "docs", "docs", run_id, "begin_dispatch", member_index=0
    )
    chop_batch_store.apply_chop_batch_event(
        "docs",
        "docs",
        run_id,
        "record_skip",
        member_index=1,
        reason="preflight skipped member",
    )
    matched_records = [
        MatchedAgentRecord(SimpleNamespace(), {"index": 0, "dedupe_key": "active-key"}),
        MatchedAgentRecord(
            SimpleNamespace(), {"index": 1, "dedupe_key": "skipped-key"}
        ),
    ]
    completions = [AgentCompletion(True, False, "failed") for _ in matched_records]
    typed_admission = {
        "units": [
            {"proposal_index": 0, "dedupe_key": "active-key"},
            {"proposal_index": 1, "dedupe_key": "skipped-key"},
        ]
    }
    released: list[list[str]] = []

    with patch(
        "sase.axe._chop_lifecycle_keys.release_chop_once_per_keys",
        side_effect=lambda _routine, _job, keys: (
            released.append(list(keys)) or len(keys)
        ),
    ):
        release_failed_launch_keys(
            lumberjack_name="docs",
            chop_name="docs",
            run_id=run_id,
            matched_records=matched_records,
            completions=completions,
        )
        release_typed_nonlaunched_keys(
            lumberjack_name="docs",
            chop_name="docs",
            run_id=run_id,
            keys=["active-key", "skipped-key"],
            typed_admission=typed_admission,
        )

    assert released == [["skipped-key"], ["skipped-key"]]


def test_lifecycle_preserves_script_duration_ms_through_finalization(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120000_000000"
    launched_entry(run_id, pid=321, script_duration_ms=250)
    record_agent(run_id, pid=321)
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
    # duration_ms is overwritten with the agent-lifetime span, but
    # script_duration_ms keeps the script's own wall-clock value.
    assert entry.duration_ms != 250
    assert entry.script_duration_ms == 250


def test_lifecycle_fails_dead_agent_without_done_marker(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120001_000000"
    launched_entry(run_id, pid=654)
    record_agent(run_id, pid=654)

    with (
        patch(
            "sase.axe._chop_lifecycle_completion.is_process_running", return_value=False
        ),
        patch("sase.axe._chop_lifecycle_keys.release_chop_once_per_keys") as release,
    ):
        assert finalize_launched_chop_runs("docs", ["docs"]) == 1
    release.assert_not_called()
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_failed"
    assert entry.error is not None and "without completion artifact" in entry.error


def test_lifecycle_uses_done_dismissed_bundle_when_done_marker_is_missing(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = "20260718T120002_000000"
    launched_entry(run_id, pid=987)
    record = record_agent(run_id, pid=987)
    child = SimpleNamespace(
        raw_suffix="20260718120000",
        is_workflow_child=True,
        status="KILLED",
        bundle_path="/archive/20260718120000__c0.json",
    )
    root = SimpleNamespace(
        raw_suffix="20260718120000",
        is_workflow_child=False,
        status="DONE",
        bundle_path="/archive/20260718120000.json",
    )

    with (
        patch(
            "sase.axe._chop_lifecycle_completion.is_process_running", return_value=False
        ),
        patch(
            "sase.axe._chop_lifecycle_completion.load_dismissed_bundle_summaries",
            return_value=[child, root],
        ) as load_summaries,
    ):
        completion = agent_completion(record)
        assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    assert completion.succeeded
    assert "dismissed bundle /archive/20260718120000.json" in completion.detail
    load_summaries.assert_called_with(
        suffixes={"20260718120000"},
        top_level_only=True,
        limit=None,
    )
    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_succeeded"


@pytest.mark.parametrize("status", ["FAILED", "KILLED"])
def test_lifecycle_uses_failed_dismissed_bundle_when_done_marker_is_missing(
    temp_state_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    run_id = f"20260718T120003_{status.lower()}"
    launched_entry(run_id, pid=876)
    record_agent(run_id, pid=876)
    summary = SimpleNamespace(
        raw_suffix="20260718120000",
        is_workflow_child=False,
        status=status,
        bundle_path="/archive/20260718120000.json",
    )

    with (
        patch(
            "sase.axe._chop_lifecycle_completion.is_process_running", return_value=False
        ),
        patch(
            "sase.axe._chop_lifecycle_completion.load_dismissed_bundle_summaries",
            return_value=[summary],
        ),
    ):
        assert finalize_launched_chop_runs("docs", ["docs"]) == 1

    entry = read_chop_run("docs", "docs", run_id)
    assert entry is not None
    assert entry.status == "action_failed"
    assert entry.error is not None
    assert "dismissed bundle /archive/20260718120000.json" in entry.error
    assert f"status {status}" in entry.error
