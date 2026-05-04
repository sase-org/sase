"""Golden tests for the agent-artifact scan facade.

Pins the snapshot wire shape, error counters, and ordering produced by
:func:`sase.core.agent_scan_facade.scan_agent_artifacts` against the
synthetic corpus in :mod:`tests.agent_scan_golden`. The facade calls
``sase_core_rs`` directly through
:func:`sase.core.rust.require_rust_binding`; the tests at the bottom of
this file pin the direct-Rust contract.
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from sase.core.agent_scan_facade import (
    scan_agent_artifacts,
    verify_agent_artifact_index,
    with_options,
)
from sase.core.agent_scan_wire import (
    AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactIndexQueryWire,
    AgentArtifactIndexUpdateWire,
    AgentArtifactScanOptionsWire,
    agent_artifact_index_query_to_dict,
    agent_artifact_index_update_from_dict,
    agent_scan_wire_to_json_dict,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME

from .agent_scan_golden import (
    EXPECTED_DECODE_ERRORS,
    EXPECTED_OS_ERRORS,
    EXPECTED_TIMESTAMPS,
    build_fixture_tree,
    fixture_summary,
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


@pytest.fixture()
def fixture_root(tmp_path: Path) -> Path:
    return build_fixture_tree(tmp_path / "projects")


def _record_by_timestamp(snapshot, timestamp: str):
    matches = [r for r in snapshot.records if r.timestamp == timestamp]
    assert len(matches) == 1, f"expected exactly one record with ts={timestamp}"
    return matches[0]


def test_schema_version_pinned() -> None:
    """Bumping the schema is a deliberate, reviewable event."""
    assert AGENT_SCAN_WIRE_SCHEMA_VERSION == 1
    assert AGENT_ARTIFACT_INDEX_SCHEMA_VERSION == 1


def test_artifact_index_wire_helpers() -> None:
    query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=False,
        include_full_history=True,
        recent_completed_limit=None,
        include_hidden=True,
    )
    assert agent_artifact_index_query_to_dict(query) == {
        "include_active": True,
        "include_recent_completed": False,
        "include_full_history": True,
        "recent_completed_limit": None,
        "include_hidden": True,
    }

    update = agent_artifact_index_update_from_dict(
        {
            "schema_version": 1,
            "index_path": "/tmp/index.sqlite",
            "projects_root": "/tmp/projects",
            "rows_indexed": 2,
            "rows_deleted": 1,
            "rows_skipped": 3,
        }
    )
    assert update == AgentArtifactIndexUpdateWire(
        schema_version=1,
        index_path="/tmp/index.sqlite",
        projects_root="/tmp/projects",
        rows_indexed=2,
        rows_deleted=1,
        rows_skipped=3,
    )


def test_fixture_summary_matches_expectations() -> None:
    """Pin the fixture's surface area so adding a branch forces a test update."""
    summary = fixture_summary()
    assert summary["timestamps"] == list(EXPECTED_TIMESTAMPS)
    assert summary["expected_decode_errors"] == EXPECTED_DECODE_ERRORS
    assert summary["expected_os_errors"] == EXPECTED_OS_ERRORS


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
    rec = _record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)
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
    rec = _record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)

    assert rec.agent_meta is not None
    assert rec.agent_meta.auto_approve_plan_action == "epic"


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
    rec = _record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)

    assert rec.agent_meta is not None
    assert rec.agent_meta.plan_submitted_at == [timestamp]
    assert rec.agent_meta.epic_started_at == epic_timestamp


def test_done_record_parses_done_marker(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = _record_by_timestamp(snapshot, TS_ACE_RUN_DONE)
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
    rec = _record_by_timestamp(snapshot, TS_ACE_RUN_FAILED)
    assert rec.done is not None
    assert rec.done.outcome == "failed"
    assert rec.done.error == "RuntimeError: kaboom"
    assert rec.done.traceback is not None and "Traceback" in rec.done.traceback


def test_retried_records_link_via_lineage_fields(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    parent = _record_by_timestamp(snapshot, TS_ACE_RUN_RETRIED_PARENT)
    child = _record_by_timestamp(snapshot, TS_ACE_RUN_RETRIED_CHILD)

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
    rec = _record_by_timestamp(snapshot, TS_HOME_RUNNING)
    assert rec.project_name == "home"
    assert rec.workflow_dir_name == "ace-run"
    assert rec.running is not None
    assert rec.running.pid == 11111
    assert rec.running.cl_name == "~"
    assert rec.running.workspace_dir == "/tmp/home-target"
    assert rec.raw_prompt_snippet == "Investigate the failing job"


def test_workflow_root_record_has_state_and_steps(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = _record_by_timestamp(snapshot, TS_WORKFLOW_ROOT)
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
    rec = _record_by_timestamp(snapshot, TS_MENTOR_DONE)
    assert rec.workflow_dir_name == "mentor-bryan"
    assert rec.done is not None
    assert rec.done.outcome == "completed"
    assert rec.done.response_path == "/tmp/mentor.md"
    # No agent_meta.json was written; the wire keeps it as None.
    assert rec.agent_meta is None


def test_waiting_marker_decode_error_does_not_crash(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = _record_by_timestamp(snapshot, TS_WAITING)
    # waiting.json was malformed; the wire reports None and the scan
    # counts the decode error.
    assert rec.waiting is None
    assert rec.agent_meta is not None
    assert rec.agent_meta.wait_for == ["upstream"]
    assert rec.agent_meta.wait_duration == 600.0


def test_malformed_agent_meta_is_skipped(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = _record_by_timestamp(snapshot, TS_MALFORMED)
    # The directory was visited so the record exists, but agent_meta is
    # None because the file failed to decode.
    assert rec.agent_meta is None
    assert rec.has_done_marker is False
    assert rec.done is None


def test_only_workflow_dirs_filters_records(fixture_root: Path) -> None:
    options = AgentArtifactScanOptionsWire(only_workflow_dirs=("ace-run",))
    snapshot = scan_agent_artifacts(fixture_root, options=options)
    workflow_dirs = {r.workflow_dir_name for r in snapshot.records}
    assert workflow_dirs == {"ace-run"}


def test_disable_prompt_step_markers(fixture_root: Path) -> None:
    base = AgentArtifactScanOptionsWire()
    options = with_options(base, include_prompt_step_markers=False)
    snapshot = scan_agent_artifacts(fixture_root, options=options)
    rec = _record_by_timestamp(snapshot, TS_WORKFLOW_ROOT)
    assert rec.prompt_steps == []
    assert snapshot.stats.prompt_step_markers_parsed == 0


def test_disable_raw_prompt_snippet(fixture_root: Path) -> None:
    options = AgentArtifactScanOptionsWire(include_raw_prompt_snippets=False)
    snapshot = scan_agent_artifacts(fixture_root, options=options)
    rec = _record_by_timestamp(snapshot, TS_HOME_RUNNING)
    assert rec.raw_prompt_snippet is None


def test_max_prompt_snippet_bytes_truncates(fixture_root: Path) -> None:
    # The fixture writes a 28-byte prompt; pick a smaller cap to force
    # truncation and verify the byte-count semantics.
    options = AgentArtifactScanOptionsWire(max_prompt_snippet_bytes=10)
    snapshot = scan_agent_artifacts(fixture_root, options=options)
    rec = _record_by_timestamp(snapshot, TS_HOME_RUNNING)
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

    done_rec = _record_by_timestamp(snapshot, TS_ACE_RUN_DONE)
    assert done_rec.has_done_marker is True
    assert done_rec.done is None

    workflow_rec = _record_by_timestamp(snapshot, TS_WORKFLOW_ROOT)
    assert workflow_rec.workflow_state is None
    waiting_rec = _record_by_timestamp(snapshot, TS_WAITING)
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


def _install_fake_scan_module(
    monkeypatch: pytest.MonkeyPatch,
    scan_fn,
) -> types.ModuleType:
    """Register a fake ``sase_core_rs`` exposing ``scan_agent_artifacts``."""
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.scan_agent_artifacts = scan_fn  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    return fake


def _minimal_snapshot(
    projects_root: str, records: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
        "projects_root": projects_root,
        "options": {},
        "stats": {
            "projects_visited": 0,
            "artifact_dirs_visited": len(records),
            "marker_files_parsed": 0,
            "json_decode_errors": 0,
            "os_errors": 0,
            "prompt_step_markers_parsed": 0,
        },
        "records": records,
    }


def _minimal_record(root: Path, timestamp: str, name: str) -> dict[str, Any]:
    artifact_dir = root / "myproj" / "artifacts" / "ace-run" / timestamp
    return {
        "project_name": "myproj",
        "project_dir": str(root / "myproj"),
        "project_file": str(root / "myproj" / "myproj.gp"),
        "workflow_dir_name": "ace-run",
        "artifact_dir": str(artifact_dir),
        "timestamp": timestamp,
        "agent_meta": {"name": name},
        "done": None,
        "running": None,
        "waiting": None,
        "workflow_state": None,
        "plan_path": None,
        "prompt_steps": [],
        "raw_prompt_snippet": None,
        "has_done_marker": False,
    }


def test_verify_agent_artifact_index_reports_clean_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_root = tmp_path / "projects"
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    record = _minimal_record(projects_root, "20260504121212", "active")

    def fake_scan(projects_root_arg: str, options: dict[str, Any]) -> dict[str, Any]:
        return _minimal_snapshot(projects_root_arg, [record])

    fake = _install_fake_scan_module(monkeypatch, fake_scan)
    fake.query_agent_artifact_index = (  # type: ignore[attr-defined]
        lambda index_arg, root_arg, query, options: _minimal_snapshot(
            root_arg, [record]
        )
    )

    result = verify_agent_artifact_index(index_path, projects_root)

    assert result.ok is True
    assert result.indexed_rows == 1
    assert result.source_rows == 1
    assert result.missing_rows == 0
    assert result.stale_rows == 0


def test_verify_agent_artifact_index_reports_stale_and_missing_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_root = tmp_path / "projects"
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    source_record = _minimal_record(projects_root, "20260504121212", "new-name")
    indexed_record = _minimal_record(projects_root, "20260504121212", "old-name")
    missing_record = _minimal_record(projects_root, "20260504131313", "missing")

    def fake_scan(projects_root_arg: str, options: dict[str, Any]) -> dict[str, Any]:
        return _minimal_snapshot(projects_root_arg, [source_record, missing_record])

    fake = _install_fake_scan_module(monkeypatch, fake_scan)
    fake.query_agent_artifact_index = (  # type: ignore[attr-defined]
        lambda index_arg, root_arg, query, options: _minimal_snapshot(
            root_arg, [indexed_record]
        )
    )

    result = verify_agent_artifact_index(index_path, projects_root)

    assert result.ok is False
    assert result.indexed_rows == 1
    assert result.source_rows == 2
    assert result.stale_rows == 1
    assert result.missing_rows == 1


def test_verify_agent_artifact_index_reports_missing_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_root = tmp_path / "projects"
    record = _minimal_record(projects_root, "20260504121212", "active")

    def fake_scan(projects_root_arg: str, options: dict[str, Any]) -> dict[str, Any]:
        return _minimal_snapshot(projects_root_arg, [record])

    _install_fake_scan_module(monkeypatch, fake_scan)

    result = verify_agent_artifact_index(
        tmp_path / "missing.sqlite",
        projects_root,
    )

    assert result.ok is False
    assert result.schema_version == 0
    assert result.indexed_rows == 0
    assert result.missing_rows == 1


def test_scan_agent_artifacts_calls_rust_binding(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The facade calls ``sase_core_rs.scan_agent_artifacts`` directly.

    Phase 8D removed the Python walker fallback; the facade now always
    delegates to the Rust binding through
    :func:`sase.core.rust.require_rust_binding`. The fake binding records
    the arguments it receives and returns a synthetic empty snapshot so
    we can assert on the dict shape the facade hands the Rust side.
    """
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_scan(projects_root: str, options: dict[str, Any]) -> dict[str, Any]:
        calls.append((projects_root, options))
        return {
            "schema_version": AGENT_SCAN_WIRE_SCHEMA_VERSION,
            "projects_root": projects_root,
            "options": options,
            "stats": {
                "projects_visited": 0,
                "artifact_dirs_visited": 0,
                "marker_files_parsed": 0,
                "json_decode_errors": 0,
                "os_errors": 0,
                "prompt_step_markers_parsed": 0,
            },
            "records": [],
        }

    _install_fake_scan_module(monkeypatch, fake_scan)

    snapshot = scan_agent_artifacts(fixture_root)
    assert snapshot.records == []
    assert len(calls) == 1
    assert calls[0][0] == str(fixture_root)
    # The facade always populates the options dict so the Rust side never
    # has to guess defaults — keys match the wire schema.
    options_dict = calls[0][1]
    assert options_dict["include_prompt_step_markers"] is True
    assert options_dict["include_raw_prompt_snippets"] is True
    assert options_dict["only_workflow_dirs"] == []
    assert options_dict["max_records"] is None
    assert options_dict["newest_first"] is False
    assert options_dict["not_before_timestamp"] is None
    assert options_dict["include_done_markers"] is True
    assert options_dict["include_workflow_state"] is True
    assert options_dict["include_waiting"] is True
    assert options_dict["only_projects"] == []


def test_scan_agent_artifacts_missing_extension_raises_importerror(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the wheel is gone, the facade raises :class:`ImportError`."""
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)

    def fail(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr("importlib.import_module", fail)
    with pytest.raises(ImportError, match=RUST_EXTENSION_MODULE_NAME):
        scan_agent_artifacts(fixture_root)


def test_scan_agent_artifacts_stale_wheel_raises_attributeerror(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wheel without the binding raises :class:`AttributeError` naming the op."""
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    with pytest.raises(AttributeError, match="scan_agent_artifacts"):
        scan_agent_artifacts(fixture_root)


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
