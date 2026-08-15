"""Shared fixtures for ``sase var`` get/list CLI tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.core.agent_scan_facade import rebuild_agent_artifact_index
from sase.project_display_names import invalidate_project_display_snapshot


def isolate_sase_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    """Point SASE state at *tmp_path* and return ``(home, projects_root)``."""
    home = tmp_path / "sase-home"
    projects = home / "projects"
    projects.mkdir(parents=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    invalidate_project_display_snapshot()
    return home, projects


def write_indexed_agent(
    projects_root: Path,
    *,
    project: str,
    timestamp: str,
    name: str,
    variables: dict[str, Any] | None = None,
    hidden: bool = False,
) -> Path:
    """Write one ace-run artifact directory with optional output variables."""
    artifact = projects_root / project / "artifacts" / "ace-run" / timestamp
    artifact.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {"name": name}
    if hidden:
        meta["hidden"] = True
    if variables is not None:
        meta["output_variables"] = variables
    (artifact / "agent_meta.json").write_text(
        json.dumps(meta),
        encoding="utf-8",
    )
    return artifact


def rebuild_home_index(home: Path, projects_root: Path) -> Path:
    """Rebuild the default artifact index under an isolated SASE home."""
    index = home / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index, projects_root)
    return index
