"""Golden tests for agent-artifact scan records.

Pins the snapshot wire shape, error counters, and ordering produced by
``sase.core.agent_scan_facade.scan_agent_artifacts`` against the synthetic
corpus in ``tests.agent_scan_golden``.
"""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import AGENT_SCAN_WIRE_SCHEMA_VERSION

from .agent_scan_golden import (
    EXPECTED_DECODE_ERRORS,
    EXPECTED_OS_ERRORS,
    EXPECTED_TIMESTAMPS,
)
from .agent_scan_golden.fixture_builder import (
    TS_ACE_RUN_DONE,
    TS_ACE_RUN_FAILED,
    TS_ACE_RUN_RETRIED_CHILD,
    TS_ACE_RUN_RETRIED_PARENT,
    TS_ACE_RUN_RUNNING,
    TS_HOME_RUNNING,
    TS_MALFORMED,
    TS_MENTOR_DONE,
    TS_WAITING,
    TS_WORKFLOW_ROOT,
)
from .core_agent_scan_helpers import (
    core_agent_scan_fixture_root as _fixture_root,
    record_by_timestamp,
)


def test_scan_returns_one_record_per_artifact_dir(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    timestamps = [r.timestamp for r in snapshot.records]
    # Every fixture artifact directory must show up exactly once.
    assert sorted(timestamps) == sorted(EXPECTED_TIMESTAMPS)
    assert snapshot.schema_version == AGENT_SCAN_WIRE_SCHEMA_VERSION
    assert snapshot.projects_root == str(fixture_root)


def test_records_are_sorted_deterministically(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    keys = [
        (r.project_name, r.workflow_dir_name, r.timestamp) for r in snapshot.records
    ]
    assert keys == sorted(keys)


def test_stats_count_decode_errors(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    assert snapshot.stats.json_decode_errors == EXPECTED_DECODE_ERRORS
    assert snapshot.stats.os_errors == EXPECTED_OS_ERRORS
    assert snapshot.stats.projects_visited == 2  # home + myproj
    assert snapshot.stats.artifact_dirs_visited == len(EXPECTED_TIMESTAMPS)
    # marker_files_parsed only counts successful parses; it should be at
    # least the number of agent_meta.json files we wrote successfully (8:
    # all timestamps except the bare home_running has agent_meta and
    # waiting has agent_meta, malformed does not have a parseable one,
    # mentor-done has only done.json).
    assert snapshot.stats.marker_files_parsed > 0
    assert snapshot.stats.prompt_step_markers_parsed == 3


def test_running_record_carries_agent_meta(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)
    assert rec.workflow_dir_name == "ace-run"
    assert rec.project_name == "myproj"
    assert rec.has_done_marker is False
    assert rec.done is None
    assert rec.agent_meta is not None
    assert rec.agent_meta.name == "running_alpha"
    assert rec.agent_meta.workflow_name == "wf_alpha"
    assert rec.agent_meta.pid == 22222
    assert rec.agent_meta.plan is True
    assert rec.agent_meta.plan_approved is False
    assert rec.agent_meta.wait_for == ["bob", "carol"]
    assert rec.agent_meta.wait_duration == 3600.0
    assert rec.agent_meta.workspace_dir == "/tmp/workspaces/alpha"


def test_running_record_carries_auto_approve_plan_action(
    fixture_root: Path,
) -> None:
    meta_path = (
        fixture_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_RUNNING
        / "agent_meta.json"
    )
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["auto_approve_plan_action"] = "epic"
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)

    assert rec.agent_meta is not None
    assert rec.agent_meta.auto_approve_plan_action == "epic"


def test_running_record_carries_agent_meta_tag(fixture_root: Path) -> None:
    meta_path = (
        fixture_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_RUNNING
        / "agent_meta.json"
    )
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["tag"] = "sase-26"
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)

    assert rec.agent_meta is not None
    assert rec.agent_meta.tag == "sase-26"


def test_scalar_plan_submitted_at_is_preserved(fixture_root: Path) -> None:
    timestamp = "2026-04-27T11:05:00Z"
    epic_timestamp = "2026-04-27T11:08:00Z"
    meta_path = (
        fixture_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_RUNNING
        / "agent_meta.json"
    )
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["plan_submitted_at"] = timestamp
    data["epic_started_at"] = epic_timestamp
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)

    assert rec.agent_meta is not None
    assert rec.agent_meta.plan_submitted_at == [timestamp]
    assert rec.agent_meta.epic_started_at == epic_timestamp


def test_done_record_parses_done_marker(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_DONE)
    assert rec.has_done_marker is True
    assert rec.done is not None
    assert rec.done.outcome == "completed"
    assert rec.done.cl_name == "feature_alpha"
    assert rec.done.workspace_num == 3
    assert rec.done.workspace_dir == "/tmp/workspaces/alpha_3"
    assert rec.done.diff_path == "/tmp/diff_alpha.diff"
    assert rec.done.markdown_pdf_paths == ["/tmp/markdown_pdfs/notes.pdf"]
    assert rec.done.image_paths == []
    assert rec.done.response_path == "/tmp/resp_alpha.md"
    assert rec.done.output_path == "/tmp/out_alpha.log"
    # The agent_meta.json adds a stopped_at timestamp.
    assert rec.agent_meta is not None
    assert rec.agent_meta.stopped_at == "2026-04-27T12:05:00Z"


def test_failed_record_carries_error_and_traceback(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_ACE_RUN_FAILED)
    assert rec.done is not None
    assert rec.done.outcome == "failed"
    assert rec.done.error == "RuntimeError: kaboom"
    assert rec.done.traceback is not None and "Traceback" in rec.done.traceback


def test_retried_records_link_via_lineage_fields(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    parent = record_by_timestamp(snapshot, TS_ACE_RUN_RETRIED_PARENT)
    child = record_by_timestamp(snapshot, TS_ACE_RUN_RETRIED_CHILD)

    assert parent.done is not None
    assert parent.done.retried_as_timestamp == TS_ACE_RUN_RETRIED_CHILD
    assert parent.done.retry_chain_root_timestamp == TS_ACE_RUN_RETRIED_PARENT
    assert parent.done.retry_error_category == "transient"
    assert parent.agent_meta is not None
    assert parent.agent_meta.retry_terminal is True

    assert child.agent_meta is not None
    assert child.agent_meta.retry_of_timestamp == TS_ACE_RUN_RETRIED_PARENT
    assert child.agent_meta.retry_attempt == 1
    assert child.agent_meta.retry_chain_root_timestamp == TS_ACE_RUN_RETRIED_PARENT
    assert child.has_done_marker is False  # the child is still running


def test_home_running_record_has_running_marker(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_HOME_RUNNING)
    assert rec.project_name == "home"
    assert rec.workflow_dir_name == "ace-run"
    assert rec.running is not None
    assert rec.running.pid == 11111
    assert rec.running.cl_name == "~"
    assert rec.running.workspace_dir == "/tmp/home-target"
    assert rec.raw_prompt_snippet == "Investigate the failing job"


def test_workflow_root_record_has_state_and_steps(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_WORKFLOW_ROOT)
    assert rec.workflow_dir_name == "workflow-three_phase"
    assert rec.workflow_state is not None
    state = rec.workflow_state
    assert state.workflow_name == "three_phase"
    assert state.cl_name == "feature_workflow"
    assert state.status == "completed"
    assert state.appears_as_agent is True
    assert state.is_anonymous is False
    assert len(state.steps) == 3
    assert state.steps[0].name == "plan"
    assert state.steps[0].status == "completed"
    assert state.steps[0].output == {"plan_path": "/tmp/plan.md"}
    assert state.steps[0].output_types == {"plan_path": "path"}

    # plan_path.json projects through.
    assert rec.plan_path is not None
    assert rec.plan_path.plan_path == "/tmp/plan.md"

    # Three prompt-step markers, sorted by file name (the leading
    # zero-padded index matches the sort order).
    assert [m.file_name for m in rec.prompt_steps] == [
        "prompt_step_000_pre.json",
        "prompt_step_001_plan.json",
        "prompt_step_002_code.json",
    ]
    pre, plan, code = rec.prompt_steps
    assert pre.is_pre_prompt_step is True
    assert pre.embedded_workflow_name == "three_phase"
    assert plan.output is not None and plan.output.get("meta_workspace") == "5"
    assert code.hidden is True
    assert code.diff_path == "/tmp/diff.diff"


def test_mentor_dir_is_walked(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_MENTOR_DONE)
    assert rec.workflow_dir_name == "mentor-bryan"
    assert rec.done is not None
    assert rec.done.outcome == "completed"
    assert rec.done.response_path == "/tmp/mentor.md"
    # No agent_meta.json was written; the wire keeps it as None.
    assert rec.agent_meta is None


def test_waiting_marker_decode_error_does_not_crash(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_WAITING)
    # waiting.json was malformed; the wire reports None and the scan
    # counts the decode error.
    assert rec.waiting is None
    assert rec.agent_meta is not None
    assert rec.agent_meta.wait_for == ["upstream"]
    assert rec.agent_meta.wait_duration == 600.0


def test_malformed_agent_meta_is_skipped(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = record_by_timestamp(snapshot, TS_MALFORMED)
    # The directory was visited so the record exists, but agent_meta is
    # None because the file failed to decode.
    assert rec.agent_meta is None
    assert rec.has_done_marker is False
    assert rec.done is None
