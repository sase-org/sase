"""Shared builders and test hooks for ``sase.history.vcs_xprompt_mru`` tests.

The MRU suite is split by concern -- raw store reads/writes, launchability
pruning, and display-name humanization -- and every module needs the same
``_MRU_FILE`` override plus the same on-disk ``ProjectSpec`` builders.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest


@contextmanager
def patched_mru_file(path: Path) -> Iterator[None]:
    """Point the module-level ``_MRU_FILE`` test hook at *path*."""
    module = __import__("sase.history.vcs_xprompt_mru", fromlist=["_MRU_FILE"])
    with patch.object(module, "_MRU_FILE", path):
        yield


def patch_discovered_workflow_type_as_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make project discovery report every project file as bare git."""
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.detect_workflow_type",
        lambda _project_file: "git",
    )


def write_project(
    projects_dir: Path, project_name: str, workspace_dir: Path | None
) -> None:
    project_dir = projects_dir / project_name
    project_dir.mkdir(parents=True)
    project_file = project_dir / f"{project_name}.sase"
    if workspace_dir is None:
        project_file.write_text("", encoding="utf-8")
        return
    project_file.write_text(
        f"WORKSPACE_DIR: {workspace_dir}\nNAME: {project_name}_change\n",
        encoding="utf-8",
    )


def write_named_project(
    projects_dir: Path,
    directory_key: str,
    project_name: str,
    workspace_dir: Path,
) -> None:
    """Write a real ProjectSpec whose ``PROJECT_NAME`` differs from its dir key."""
    project_dir = projects_dir / directory_key
    project_dir.mkdir(parents=True)
    (project_dir / f"{directory_key}.sase").write_text(
        f"PROJECT_NAME: {project_name}\nWORKSPACE_DIR: {workspace_dir}\n"
        f"NAME: {directory_key}_change\n",
        encoding="utf-8",
    )
