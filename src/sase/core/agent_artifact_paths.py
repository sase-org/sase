"""Shared helpers for SASE agent artifact directory layout."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.paths import sase_projects_dir
from sase.core.rust import require_rust_binding

ACE_RUN_WORKFLOW_DIR = "ace-run"
LEGACY_LAYOUT_VERSION = 1
DAY_SHARDED_LAYOUT_VERSION = 2


@dataclass(frozen=True)
class _AgentArtifactPathInfo:
    project_name: str
    workflow_dir_name: str
    timestamp: str
    artifact_dir: str
    layout_version: int


def _projects_root(projects_root: Path | str | None = None) -> Path:
    return Path(projects_root).expanduser() if projects_root else sase_projects_dir()


def canonical_agent_artifact_path(
    project_name: str,
    workflow_dir_name: str,
    timestamp: str,
    *,
    projects_root: Path | str | None = None,
) -> Path:
    """Return the canonical physical artifact path for one timestamp."""
    binding = require_rust_binding("canonical_agent_artifact_path")
    return Path(
        binding(
            str(_projects_root(projects_root)),
            project_name,
            workflow_dir_name,
            timestamp,
        )
    )


def resolve_agent_artifact_path(
    artifact_dir: Path | str,
    *,
    projects_root: Path | str | None = None,
) -> Path:
    """Resolve a legacy or sharded artifact path to the current physical path."""
    binding = require_rust_binding("resolve_agent_artifact_path")
    return Path(binding(str(_projects_root(projects_root)), str(Path(artifact_dir))))


def resolve_agent_artifact_timestamp_path(
    project_name: str,
    workflow_dir_name: str,
    timestamp: str,
    *,
    projects_root: Path | str | None = None,
) -> Path:
    """Resolve a project/workflow/timestamp tuple to the existing path if present."""
    binding = require_rust_binding("resolve_agent_artifact_timestamp_path")
    return Path(
        binding(
            str(_projects_root(projects_root)),
            project_name,
            workflow_dir_name,
            timestamp,
        )
    )


def parse_agent_artifact_path(
    artifact_dir: Path | str,
    *,
    projects_root: Path | str | None = None,
) -> _AgentArtifactPathInfo | None:
    """Parse a legacy or sharded artifact path."""
    binding = require_rust_binding("parse_agent_artifact_path")
    payload: dict[str, Any] | None = binding(
        str(_projects_root(projects_root)),
        str(Path(artifact_dir)),
    )
    if payload is None:
        return None
    return _AgentArtifactPathInfo(
        project_name=str(payload["project_name"]),
        workflow_dir_name=str(payload["workflow_dir_name"]),
        timestamp=str(payload["timestamp"]),
        artifact_dir=str(payload["artifact_dir"]),
        layout_version=int(payload["layout_version"]),
    )


def iter_agent_artifact_dirs(
    project_name: str,
    workflow_dir_name: str = ACE_RUN_WORKFLOW_DIR,
    *,
    projects_root: Path | str | None = None,
    newest_first: bool = False,
) -> Iterator[Path]:
    """Yield artifact dirs for one project/workflow across supported layouts."""
    binding = require_rust_binding("iter_agent_artifact_dirs")
    for path in binding(
        str(_projects_root(projects_root)),
        project_name,
        workflow_dir_name,
        newest_first,
    ):
        yield Path(path)


__all__ = [
    "ACE_RUN_WORKFLOW_DIR",
    "DAY_SHARDED_LAYOUT_VERSION",
    "LEGACY_LAYOUT_VERSION",
    "canonical_agent_artifact_path",
    "iter_agent_artifact_dirs",
    "parse_agent_artifact_path",
    "resolve_agent_artifact_path",
    "resolve_agent_artifact_timestamp_path",
]
