from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.core.agent_scan_facade import scan_agent_artifacts, with_options
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactScanOptionsWire,
    agent_scan_wire_to_json_dict,
)

from .agent_scan_golden.fixture_builder import (
    TS_ACE_RUN_DONE,
    TS_ACE_RUN_RETRIED_PARENT,
    TS_ACE_RUN_RUNNING,
    TS_HOME_RUNNING,
    TS_MENTOR_DONE,
    TS_WAITING,
    TS_WORKFLOW_ROOT,
)
from .core_agent_scan_helpers import (
    core_agent_scan_fixture_root as _fixture_root,
    record_by_timestamp,
)


def test_only_workflow_dirs_filters_records(fixture_root: Path) -> None:
    options = AgentArtifactScanOptionsWire(only_workflow_dirs=("ace-run",))
    snapshot = scan_agent_artifacts(fixture_root, options=options)
    workflow_dirs = {r.workflow_dir_name for r in snapshot.records}
    assert workflow_dirs == {"ace-run"}


def test_disable_prompt_step_markers(fixture_root: Path) -> None:
    base = AgentArtifactScanOptionsWire()
    options = with_options(base, include_prompt_step_markers=False)
    snapshot = scan_agent_artifacts(fixture_root, options=options)
    rec = record_by_timestamp(snapshot, TS_WORKFLOW_ROOT)
    assert rec.prompt_steps == []
    assert snapshot.stats.prompt_step_markers_parsed == 0


def test_disable_raw_prompt_snippet(fixture_root: Path) -> None:
    options = AgentArtifactScanOptionsWire(include_raw_prompt_snippets=False)
    snapshot = scan_agent_artifacts(fixture_root, options=options)
    rec = record_by_timestamp(snapshot, TS_HOME_RUNNING)
    assert rec.raw_prompt_snippet is None


def test_max_prompt_snippet_bytes_truncates(fixture_root: Path) -> None:
    # The fixture writes a 28-byte prompt; pick a smaller cap to force
    # truncation and verify the byte-count semantics.
    options = AgentArtifactScanOptionsWire(max_prompt_snippet_bytes=10)
    snapshot = scan_agent_artifacts(fixture_root, options=options)
    rec = record_by_timestamp(snapshot, TS_HOME_RUNNING)
    assert rec.raw_prompt_snippet == "Investigat"


def test_missing_root_returns_empty_snapshot(tmp_path: Path) -> None:
    snapshot = scan_agent_artifacts(tmp_path / "does_not_exist")
    assert snapshot.records == []
    assert snapshot.stats.projects_visited == 0
    assert snapshot.stats.artifact_dirs_visited == 0
    assert snapshot.stats.json_decode_errors == 0


def test_options_round_trip_through_snapshot(fixture_root: Path) -> None:
    options = AgentArtifactScanOptionsWire(
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
        max_prompt_snippet_bytes=42,
        only_workflow_dirs=("ace-run", "workflow-three_phase"),
        max_records=3,
        newest_first=True,
        not_before_timestamp="20260427120000",
        include_done_markers=False,
        include_workflow_state=False,
        include_waiting=False,
        only_projects=("myproj",),
    )
    snapshot = scan_agent_artifacts(fixture_root, options=options)
    assert snapshot.options == options


def test_bounded_newest_first_limits_completed_without_hiding_incomplete(
    fixture_root: Path,
) -> None:
    options = AgentArtifactScanOptionsWire(max_records=2, newest_first=True)
    snapshot = scan_agent_artifacts(fixture_root, options=options)
    timestamps = [r.timestamp for r in snapshot.records]
    completed = [r.timestamp for r in snapshot.records if r.has_done_marker]

    assert completed == [TS_MENTOR_DONE, TS_ACE_RUN_RETRIED_PARENT]
    assert TS_HOME_RUNNING in timestamps
    assert TS_ACE_RUN_RUNNING in timestamps
    assert TS_WAITING in timestamps
    assert timestamps == sorted(timestamps, reverse=True)


def test_selective_marker_options_skip_payloads_but_keep_done_presence(
    fixture_root: Path,
) -> None:
    options = AgentArtifactScanOptionsWire(
        include_done_markers=False,
        include_waiting=False,
        include_workflow_state=False,
    )
    snapshot = scan_agent_artifacts(fixture_root, options=options)

    done_rec = record_by_timestamp(snapshot, TS_ACE_RUN_DONE)
    assert done_rec.has_done_marker is True
    assert done_rec.done is None

    workflow_rec = record_by_timestamp(snapshot, TS_WORKFLOW_ROOT)
    assert workflow_rec.workflow_state is None
    waiting_rec = record_by_timestamp(snapshot, TS_WAITING)
    assert waiting_rec.waiting is None


def test_snapshot_serializes_to_json(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    payload = agent_scan_wire_to_json_dict(snapshot)
    # Round-trips through json without surprises.
    raw = json.dumps(payload)
    assert isinstance(raw, str)
    decoded = json.loads(raw)
    assert decoded["schema_version"] == AGENT_SCAN_WIRE_SCHEMA_VERSION
    assert decoded["projects_root"] == str(fixture_root)
    assert isinstance(decoded["records"], list)
    assert all("timestamp" in r for r in decoded["records"])


def test_unsupported_workflow_dirs_are_skipped(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    weird_dir = root / "myproj" / "artifacts" / "totally_unrelated" / "20260101000000"
    weird_dir.mkdir(parents=True)
    (weird_dir / "agent_meta.json").write_text(json.dumps({"name": "ghost"}))

    snapshot = scan_agent_artifacts(root)
    assert snapshot.records == []
    # The artifacts/ dir was visited but no recognized workflow folder
    # was found.
    assert snapshot.stats.projects_visited == 1
    assert snapshot.stats.artifact_dirs_visited == 0


def test_unreadable_artifact_dir_is_counted(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("permission tests are not meaningful as root")
    root = tmp_path / "projects"
    artifact_dir = root / "myproj" / "artifacts" / "ace-run" / "20260427120000"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text(json.dumps({"name": "blocked"}))
    # Strip read perms so iterdir during prompt_step scan fails.
    os.chmod(artifact_dir, 0o000)
    try:
        snapshot = scan_agent_artifacts(root)
    finally:
        os.chmod(artifact_dir, 0o700)

    # Even when reads fail, the snapshot should not raise; the OS error
    # counter must reflect the failure.
    assert snapshot.stats.os_errors >= 1
