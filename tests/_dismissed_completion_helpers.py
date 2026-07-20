"""Fixtures for archive-backed completion regressions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sase.ace.dismissed_agents import rebuild_dismissed_bundle_index


def add_archive_identity(
    artifact_dir: Path,
    *,
    changespec_name: str = "change",
) -> dict[str, Any]:
    """Add the identity fields production ``agent_meta.json`` retains."""

    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["changespec_name"] = changespec_name
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return meta


def write_dismissed_completion(
    home: Path,
    artifact_dir: Path,
    name: str,
    *,
    status: str = "DONE",
    changespec_name: str = "change",
    project_name: str | None = None,
    response_path: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write one realistic top-level dismissed bundle without rebuilding."""

    project = project_name or artifact_dir.parents[2].name
    project_file = home / ".sase" / "projects" / project / f"{project}.sase"
    bundle: dict[str, Any] = {
        "agent_type": "workflow",
        "cl_name": changespec_name,
        "project_file": str(project_file),
        "status": status,
        "raw_suffix": artifact_dir.name,
        "artifacts_dir": str(artifact_dir),
        "agent_name": name,
        "is_workflow_child": False,
    }
    if response_path is not None:
        bundle["response_path"] = response_path
    if extra:
        bundle.update(extra)

    bundle_path = home / ".sase" / "dismissed_bundles" / f"{artifact_dir.name}.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    return bundle_path


def rebuild_completion_archive() -> None:
    rebuild_dismissed_bundle_index()
