"""Golden tests for the agent-artifact scan record envelope."""

from __future__ import annotations

from pathlib import Path

from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import AGENT_SCAN_WIRE_SCHEMA_VERSION

from .agent_scan_golden import (
    EXPECTED_DECODE_ERRORS,
    EXPECTED_OS_ERRORS,
    EXPECTED_TIMESTAMPS,
)
from .core_agent_scan_helpers import core_agent_scan_fixture_root as _fixture_root


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
