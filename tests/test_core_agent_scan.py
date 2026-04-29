"""Golden parity tests for the agent-artifact scan facade (Phase 3A/C).

Pins the snapshot wire shape, error counters, and ordering produced by
:func:`sase.core.agent_scan_facade.scan_agent_artifacts` against the
synthetic corpus in :mod:`tests.agent_scan_golden`. A future
``sase_core_rs`` implementation must reproduce these snapshots — until
then they pin the Python scanner so refactors can't drift silently.

Phase 3C tests at the bottom cover the Rust backend dispatch wiring with
a fake ``sase_core_rs`` module and (when the real extension is
installed) verify parity against the Python facade.
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
    scan_agent_artifacts_python,
    with_options,
)
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactScanOptionsWire,
    agent_scan_wire_from_dict,
    agent_scan_wire_to_json_dict,
)
from sase.core.backend import (
    BACKEND_ENV_VAR,
    DUAL_RUN_ENV_VAR,
    RUST_EXTENSION_MODULE_NAME,
    RustBackendUnavailableError,
)
from sase.core.dual_run import DUAL_RUN_LOG_OVERRIDE_ENV_VAR

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


@pytest.fixture(autouse=True)
def _clean_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure each test starts with default Python backend and no dual-run."""
    monkeypatch.delenv(BACKEND_ENV_VAR, raising=False)
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)


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


def test_scalar_plan_submitted_at_is_preserved(fixture_root: Path) -> None:
    timestamp = "2026-04-27T11:05:00Z"
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
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    snapshot = scan_agent_artifacts(fixture_root)
    rec = _record_by_timestamp(snapshot, TS_ACE_RUN_RUNNING)

    assert rec.agent_meta is not None
    assert rec.agent_meta.plan_submitted_at == [timestamp]


def test_done_record_parses_done_marker(fixture_root: Path) -> None:
    snapshot = scan_agent_artifacts(fixture_root)
    rec = _record_by_timestamp(snapshot, TS_ACE_RUN_DONE)
    assert rec.has_done_marker is True
    assert rec.done is not None
    assert rec.done.outcome == "completed"
    assert rec.done.cl_name == "feature_alpha"
    assert rec.done.workspace_num == 3
    assert rec.done.diff_path == "/tmp/diff_alpha.diff"
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


def test_python_facade_and_dispatch_agree(fixture_root: Path) -> None:
    """Calling via the dispatcher matches calling the Python impl directly."""
    direct = scan_agent_artifacts_python(fixture_root)
    via_dispatch = scan_agent_artifacts(fixture_root)
    assert agent_scan_wire_to_json_dict(direct) == agent_scan_wire_to_json_dict(
        via_dispatch
    )


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
    )
    snapshot = scan_agent_artifacts(fixture_root, options=options)
    assert snapshot.options == options


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


def _python_snapshot_as_dict(
    projects_root: str, options_dict: dict[str, Any] | None
) -> dict[str, Any]:
    """Compute the Python facade snapshot and return it as a JSON-safe dict.

    Used by fake Rust modules to mirror what a real binding would emit.
    """
    if options_dict is not None:
        opts = AgentArtifactScanOptionsWire(
            include_prompt_step_markers=bool(
                options_dict.get("include_prompt_step_markers", True)
            ),
            include_raw_prompt_snippets=bool(
                options_dict.get("include_raw_prompt_snippets", True)
            ),
            max_prompt_snippet_bytes=int(
                options_dict.get("max_prompt_snippet_bytes", 200)
            ),
            only_workflow_dirs=tuple(options_dict.get("only_workflow_dirs") or ()),
        )
    else:
        opts = AgentArtifactScanOptionsWire()
    snapshot = scan_agent_artifacts_python(projects_root, opts)
    return agent_scan_wire_to_json_dict(snapshot)


def test_scan_agent_artifacts_rust_unavailable_keeps_python(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No Rust extension + default backend = Python path, unchanged behavior."""
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)

    def fail(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr("importlib.import_module", fail)
    snapshot = scan_agent_artifacts(fixture_root)
    assert sorted(r.timestamp for r in snapshot.records)


def test_scan_agent_artifacts_rust_without_impl_raises(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``SASE_CORE_BACKEND=rust`` with no extension raises a clear error."""
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)

    def fail(name: str) -> object:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr("importlib.import_module", fail)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    with pytest.raises(RustBackendUnavailableError):
        scan_agent_artifacts(fixture_root)


def test_scan_agent_artifacts_rust_backend_uses_rust_impl(
    fixture_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``SASE_CORE_BACKEND=rust`` calls the registered Rust binding."""
    calls: list[tuple[str, dict[str, Any] | None]] = []

    def fake_scan(
        projects_root: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        calls.append((projects_root, options))
        return _python_snapshot_as_dict(projects_root, options)

    _install_fake_scan_module(monkeypatch, fake_scan)
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    snapshot = scan_agent_artifacts(fixture_root)

    assert len(calls) == 1
    assert calls[0][0] == str(fixture_root)
    # The facade always passes a populated options dict so the Rust side
    # never has to guess defaults.
    assert calls[0][1] is not None
    assert calls[0][1]["include_prompt_step_markers"] is True
    # Rust output is rehydrated into the same dataclass shape callers
    # already consume from the Python path.
    assert sorted(r.timestamp for r in snapshot.records) == sorted(EXPECTED_TIMESTAMPS)
    assert snapshot.schema_version == AGENT_SCAN_WIRE_SCHEMA_VERSION


def test_scan_agent_artifacts_dual_run_logs_comparison(
    fixture_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Dual-run runs both impls, logs one record, returns Python output."""
    log_path = tmp_path / "core_dual_run.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log_path))
    monkeypatch.setenv(DUAL_RUN_ENV_VAR, "1")

    rust_calls: list[str] = []

    def fake_scan(
        projects_root: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        rust_calls.append(projects_root)
        return _python_snapshot_as_dict(projects_root, options)

    _install_fake_scan_module(monkeypatch, fake_scan)

    snapshot = scan_agent_artifacts(fixture_root)

    # Python output is what the caller sees, even under dual-run.
    assert sorted(r.timestamp for r in snapshot.records) == sorted(EXPECTED_TIMESTAMPS)
    assert rust_calls == [str(fixture_root)]

    records = [
        json.loads(line) for line in log_path.read_text().splitlines() if line.strip()
    ]
    assert len(records) == 1
    rec = records[0]
    assert rec["operation"] == "scan_agent_artifacts"
    assert rec["match"] is True
    assert rec["error_class"] is None


def test_scan_agent_artifacts_dual_run_records_mismatch(
    fixture_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Mismatched Rust output is logged with ``match=False``."""
    log_path = tmp_path / "core_dual_run.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log_path))
    monkeypatch.setenv(DUAL_RUN_ENV_VAR, "1")

    def fake_scan(
        projects_root: str, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        # Drop all records so the comparison must fail.
        payload = _python_snapshot_as_dict(projects_root, options)
        payload["records"] = []
        return payload

    _install_fake_scan_module(monkeypatch, fake_scan)

    scan_agent_artifacts(fixture_root)

    records = [
        json.loads(line) for line in log_path.read_text().splitlines() if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["match"] is False


def test_rust_extension_parity(fixture_root: Path) -> None:
    """When ``sase_core_rs`` is installed, its output matches the Python facade."""
    rust_module = pytest.importorskip("sase_core_rs")
    if not hasattr(rust_module, "scan_agent_artifacts"):
        pytest.skip("sase_core_rs is too old (no scan_agent_artifacts).")

    py_snapshot = scan_agent_artifacts_python(fixture_root)
    raw = rust_module.scan_agent_artifacts(str(fixture_root), None)
    rust_snapshot = agent_scan_wire_from_dict(raw)
    assert agent_scan_wire_to_json_dict(rust_snapshot) == agent_scan_wire_to_json_dict(
        py_snapshot
    )


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
