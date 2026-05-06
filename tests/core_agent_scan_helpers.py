from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from sase.core.agent_scan_wire import AGENT_SCAN_WIRE_SCHEMA_VERSION
from sase.core.rust import RUST_EXTENSION_MODULE_NAME

from .agent_scan_golden import build_fixture_tree


@pytest.fixture(name="fixture_root")
def core_agent_scan_fixture_root(tmp_path: Path) -> Path:
    return build_fixture_tree(tmp_path / "projects")


def record_by_timestamp(snapshot, timestamp: str):
    matches = [r for r in snapshot.records if r.timestamp == timestamp]
    assert len(matches) == 1, f"expected exactly one record with ts={timestamp}"
    return matches[0]


def install_fake_scan_module(
    monkeypatch: pytest.MonkeyPatch,
    scan_fn,
) -> types.ModuleType:
    """Register a fake ``sase_core_rs`` exposing ``scan_agent_artifacts``."""
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    fake.scan_agent_artifacts = scan_fn  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    return fake


def minimal_snapshot(
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


def minimal_record(root: Path, timestamp: str, name: str) -> dict[str, Any]:
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
