"""Shared types and JSON marker helpers for the load-tiering fixture."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from sase.ace.tui.models import _agent_loader_artifacts as loader_artifacts

DEFAULT_ARCHIVE_ARTIFACT_COUNT = 13_000
FIXTURE_SCHEMA_VERSION = 2

_TUI_SCAN_OPTIONS = loader_artifacts._TUI_SCAN_OPTIONS
_PROJECTS = ("gh_sase-org__sase", "gh_bobs-org__bob-cli", "home")
_MODELS = ("gpt-5.6-sol", "claude-sonnet-5", "grok-code-fast")
_PROVIDERS = ("codex", "claude", "grok")
_BASE_TIME = datetime(2026, 9, 12, 14, 0, 0, tzinfo=UTC)


@dataclass(frozen=True)
class SyntheticArchiveFixture:
    """Materialized synthetic archive and its rebuilt index."""

    sase_home: Path
    projects_root: Path
    index_path: Path
    artifact_count: int
    active_count: int
    completed_count: int
    hidden_count: int
    workflow_count: int
    provenance_marker_count: int

    def as_dict(self) -> dict[str, int | str]:
        return {
            "sase_home": str(self.sase_home),
            "projects_root": str(self.projects_root),
            "index_path": str(self.index_path),
            "artifact_count": self.artifact_count,
            "active_count": self.active_count,
            "completed_count": self.completed_count,
            "hidden_count": self.hidden_count,
            "workflow_count": self.workflow_count,
            "provenance_marker_count": self.provenance_marker_count,
        }


def _artifact_dir(
    projects_root: Path,
    project: str,
    workflow: str,
    offset: int,
) -> Path:
    timestamp = (_BASE_TIME - timedelta(seconds=offset)).strftime("%Y%m%d%H%M%S")
    return projects_root / project / "artifacts" / workflow / timestamp


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _meta_payload(
    *,
    index: int,
    name: str,
    cl_name: str,
    provider: str,
    model: str,
    pid: int | None = None,
    hidden: bool = False,
    active: bool = False,
    provenance: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "cl_name": cl_name,
        "model": model,
        "llm_provider": provider,
        "vcs_provider": "github",
        "workspace_dir": f"/tmp/sase-load-tiering/ws-{index}",
        "run_started_at": "2026-09-12T13:00:00Z",
    }
    if pid is not None:
        payload["pid"] = pid
    if active:
        payload["fixture_active_pid"] = True
    if hidden:
        payload["hidden"] = True
    if provenance:
        payload["imported_source_owner"] = {
            "username": "bryan",
            "machine_name": "apollo",
        }
        payload["source_machine"] = "apollo"
    if not hidden and index % 11 == 0:
        payload["agent_family"] = f"family-{index // 11}"
        payload["agent_family_role"] = "code"
        payload["agent_family_parallel"] = True
    if not hidden and index % 13 == 0:
        payload["tribe"] = "bench"
    return payload


def _done_payload(
    *,
    name: str,
    cl_name: str,
    provider: str,
    model: str,
    project_file: Path,
    outcome: str = "completed",
    hidden: bool = False,
    provenance: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "outcome": outcome,
        "finished_at": 1_789_220_000.0,
        "cl_name": cl_name,
        "project_file": str(project_file),
        "workspace_num": 22,
        "workspace_dir": "/tmp/sase-load-tiering/done",
        "model": model,
        "llm_provider": provider,
        "vcs_provider": "github",
        "name": name,
        "response_path": "/tmp/sase-load-tiering/response.md",
    }
    if outcome == "failed":
        payload["error"] = "RuntimeError: fixture failure"
        payload["traceback"] = "Traceback (most recent call last): ..."
    if hidden:
        payload["hidden"] = True
    if provenance:
        payload["imported_source_owner"] = {
            "username": "bryan",
            "machine_name": "apollo",
        }
        payload["source_machine"] = "apollo"
    return payload
