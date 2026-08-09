"""Lifecycle filtering through the legacy compatibility facade."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.changespec import (
    find_all_changespecs as find_all_patches,  # legacy compatibility alias
)
from sase.ace.changespec.cache import PatchSnapshotCache


def _write_project(projects_root: Path, project: str, content: str) -> Path:
    project_dir = projects_root / project
    project_dir.mkdir(parents=True, exist_ok=True)
    project_file = project_dir / f"{project}.sase"
    project_file.write_text(content, encoding="utf-8")
    return project_file


def test_find_all_patches_defaults_to_active_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    projects_root = sase_home / "projects"

    _write_project(
        projects_root,
        "active",
        "NAME: active_change\nDESCRIPTION:\n  active\nSTATUS: Ready\n",
    )
    _write_project(
        projects_root,
        "archived",
        "PROJECT_STATE: archived\n"
        "NAME: archived_change\nDESCRIPTION:\n  archived\nSTATUS: Ready\n",
    )

    assert [cs.name for cs in find_all_patches()] == ["active_change"]
    assert [cs.name for cs in find_all_patches(include_states="all")] == [
        "active_change",
        "archived_change",
    ]


def test_find_all_patches_cached_defaults_to_active_projects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    projects_root = sase_home / "projects"

    _write_project(
        projects_root,
        "active",
        "NAME: active_change\nDESCRIPTION:\n  active\nSTATUS: Ready\n",
    )
    _write_project(
        projects_root,
        "closed",
        "PROJECT_STATE: closed\n"
        "NAME: closed_change\nDESCRIPTION:\n  closed\nSTATUS: Ready\n",
    )

    cache = PatchSnapshotCache()

    assert [cs.name for cs in cache.find_all_patches_cached()] == ["active_change"]
    assert [cs.name for cs in cache.find_all_patches_cached(include_states="all")] == [
        "active_change",
        "closed_change",
    ]
