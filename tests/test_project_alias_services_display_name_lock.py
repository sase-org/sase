"""Tests for locking a project's display name."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from sase import project_aliases
from sase import project_display_names as pdn
from sase.project_aliases import (
    _set_project_name_locked,
    ensure_project_name_locked,
)
from tests.main.project_handler_helpers import (
    _write_project,
    lifecycle_stubs,
    projects_root,
)

__all__ = ["lifecycle_stubs", "projects_root"]


def test_set_project_name_locked_writes_replaces_and_removes_name(
    projects_root: Path,
    lifecycle_stubs: Callable[[], None],
) -> None:
    lifecycle_stubs()
    project_file = _write_project(
        projects_root,
        "alpha",
        "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
    )

    record = _set_project_name_locked("alpha", "widgets", projects_root=projects_root)
    assert record.display_name == "widgets"
    assert "PROJECT_NAME: widgets\n" in project_file.read_text(encoding="utf-8")

    record = _set_project_name_locked("alpha", "tools", projects_root=projects_root)
    content = project_file.read_text(encoding="utf-8")
    assert record.display_name == "tools"
    assert "PROJECT_NAME: tools\n" in content
    assert "widgets" not in content

    record = _set_project_name_locked("alpha", None, projects_root=projects_root)
    assert record.display_name is None
    assert "PROJECT_NAME:" not in project_file.read_text(encoding="utf-8")


def test_set_project_name_locked_invalidates_display_snapshot(
    projects_root: Path,
    lifecycle_stubs: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle_stubs()
    _write_project(
        projects_root,
        "alpha",
        "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
    )
    monkeypatch.setattr(
        pdn,
        "list_project_records",
        lambda *args, **kwargs: project_aliases.list_project_records(*args, **kwargs),
    )
    monkeypatch.setattr(pdn, "_PROJECT_DISPLAY_NAME_CACHE", None)

    assert pdn.project_display_name_for("alpha", projects_root) == "alpha"

    _set_project_name_locked("alpha", "widgets", projects_root=projects_root)

    assert pdn.project_display_name_for("alpha", projects_root) == "widgets"


def test_ensure_project_name_locked_is_idempotent(
    projects_root: Path,
    lifecycle_stubs: Callable[[], None],
) -> None:
    lifecycle_stubs()
    project_file = _write_project(
        projects_root,
        "alpha",
        "PROJECT_NAME: widgets\nWORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
    )

    record = ensure_project_name_locked("alpha", "widgets", projects_root=projects_root)

    assert record.display_name == "widgets"
    assert project_file.read_text(encoding="utf-8").count("PROJECT_NAME:") == 1


def test_set_project_name_locked_rejects_alias_collision(
    projects_root: Path,
    lifecycle_stubs: Callable[[], None],
) -> None:
    lifecycle_stubs()
    project_file = _write_project(
        projects_root,
        "alpha",
        "WORKSPACE_DIR: /tmp/alpha\nNAME: a\n",
    )
    _write_project(
        projects_root,
        "beta",
        "PROJECT_ALIASES: widgets\nWORKSPACE_DIR: /tmp/beta\nNAME: b\n",
    )

    with pytest.raises(ValueError, match="assigned to both"):
        _set_project_name_locked("alpha", "widgets", projects_root=projects_root)

    assert "PROJECT_NAME:" not in project_file.read_text(encoding="utf-8")
