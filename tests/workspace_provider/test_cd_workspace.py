"""Tests for the built-in cd workspace provider."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.workspace_provider.plugins.cd_workspace import CdWorkspacePlugin


def test_cd_metadata() -> None:
    metadata = CdWorkspacePlugin().ws_get_workflow_metadata()

    assert metadata is not None
    assert metadata.workflow_type == "cd"
    assert metadata.display_name == "Directory"
    assert metadata.pre_allocated_env_prefix == "SASE_CD"
    assert metadata.vcs_family == ""
    assert metadata.vcs_provider_name == ""


def test_resolve_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    resolved = CdWorkspacePlugin().ws_resolve_ref("~", "cd")

    assert resolved is not None
    assert resolved.project_file == str(
        tmp_path / ".sase" / "projects" / "home" / "home.gp"
    )
    assert resolved.project_name == "home"
    assert resolved.checkout_target == str(tmp_path)
    assert resolved.primary_workspace_dir == str(tmp_path)


def test_resolve_absolute_path(tmp_path: Path) -> None:
    target = tmp_path / "work"
    target.mkdir()

    resolved = CdWorkspacePlugin().ws_resolve_ref(str(target), "cd")

    assert resolved is not None
    assert resolved.project_name == "work"
    assert resolved.primary_workspace_dir == str(target.resolve())
    assert resolved.checkout_target == str(target.resolve())


def test_resolve_relative_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "relative"
    target.mkdir()
    monkeypatch.chdir(tmp_path)

    resolved = CdWorkspacePlugin().ws_resolve_ref("relative", "cd")

    assert resolved is not None
    assert resolved.primary_workspace_dir == str(target.resolve())


def test_resolve_expands_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "envdir"
    target.mkdir()
    monkeypatch.setenv("SASE_TEST_CD_DIR", str(target))

    resolved = CdWorkspacePlugin().ws_resolve_ref("$SASE_TEST_CD_DIR", "cd")

    assert resolved is not None
    assert resolved.primary_workspace_dir == str(target.resolve())


def test_resolve_nonexistent_path_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        CdWorkspacePlugin().ws_resolve_ref(str(tmp_path / "missing"), "cd")


def test_resolve_file_raises(tmp_path: Path) -> None:
    file_path = tmp_path / "file.txt"
    file_path.write_text("not a dir", encoding="utf-8")

    with pytest.raises(ValueError, match="not a directory"):
        CdWorkspacePlugin().ws_resolve_ref(str(file_path), "cd")


def test_get_workspace_directory_returns_primary(tmp_path: Path) -> None:
    result = CdWorkspacePlugin().ws_get_workspace_directory(
        "cd",
        workspace_num=99,
        project_name="ignored",
        primary_workspace_dir=str(tmp_path),
    )

    assert result == str(tmp_path)
