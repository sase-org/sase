"""Tests for TUI project selection data loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.modals.project_discovery import (
    is_launchable_project,
    list_launchable_projects,
)
from sase.ace.tui.modals.project_select_modal import ProjectSelectModal


def _write_project(
    projects_dir: Path,
    project_name: str,
    workspace_dir: Path | None,
    *,
    state: str | None = None,
) -> Path:
    project_dir = projects_dir / project_name
    project_dir.mkdir(parents=True)
    project_file = project_dir / f"{project_name}.sase"
    if workspace_dir is None:
        project_file.write_text("", encoding="utf-8")
    else:
        state_line = f"PROJECT_STATE: {state}\n" if state is not None else ""
        project_file.write_text(
            f"{state_line}WORKSPACE_DIR: {workspace_dir}\n"
            f"NAME: {project_name}_change\n",
            encoding="utf-8",
        )
    return project_file


def _changespec(name: str, status: str, project_name: str = "valid") -> ChangeSpec:
    return ChangeSpec(
        name=name,
        description="description",
        parent=None,
        cl=None,
        status=status,
        file_path=f"/tmp/.sase/projects/{project_name}/{project_name}.sase",
        line_number=1,
    )


def test_list_launchable_projects_filters_invalid_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_dir = tmp_path / "projects"
    valid_workspace = tmp_path / "valid-workspace"
    inactive_workspace = tmp_path / "inactive-workspace"
    no_provider_workspace = tmp_path / "no-provider-workspace"
    home_workspace = tmp_path / "home-workspace"
    for workspace in (
        valid_workspace,
        inactive_workspace,
        no_provider_workspace,
        home_workspace,
    ):
        workspace.mkdir()

    _write_project(projects_dir, "valid", valid_workspace)
    _write_project(projects_dir, "inactive", inactive_workspace, state="inactive")
    _write_project(projects_dir, "empty", None)
    _write_project(projects_dir, "stale", tmp_path / "missing-workspace")
    _write_project(projects_dir, "no_provider", no_provider_workspace)
    _write_project(projects_dir, "home", home_workspace)
    (projects_dir / "missing_gp").mkdir()

    def detect(project_file: str) -> str:
        if "no_provider" in project_file:
            raise ValueError("not claimed")
        return "git"

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.detect_workflow_type", detect
    )

    projects = list_launchable_projects(projects_dir)

    assert projects == ["home", "valid"]
    assert is_launchable_project("valid", projects_dir) is True
    assert is_launchable_project("inactive", projects_dir) is False
    assert is_launchable_project("stale", projects_dir) is False
    assert is_launchable_project("home", projects_dir) is True


def test_home_project_must_be_real_active_and_launchable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    home_workspace = tmp_path / "home-workspace"
    inactive_home_workspace = tmp_path / "inactive-home-workspace"
    home_workspace.mkdir()
    inactive_home_workspace.mkdir()

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.detect_workflow_type",
        lambda _project_file: "git",
    )

    assert is_launchable_project("home", projects_dir) is False

    home_project_file = _write_project(projects_dir, "home", home_workspace)
    assert is_launchable_project("home", projects_dir) is True

    home_project_file.write_text(
        "PROJECT_STATE: inactive\n"
        f"WORKSPACE_DIR: {inactive_home_workspace}\n"
        "NAME: inactive_home_change\n",
        encoding="utf-8",
    )
    assert is_launchable_project("home", projects_dir) is False


def test_project_select_modal_loads_launchable_projects_and_active_changespecs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_select_modal.list_launchable_projects",
        lambda: ["home", "valid"],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_select_modal.find_all_changespecs",
        lambda: [
            _changespec("valid_active", "Ready"),
            _changespec("valid_submitted", "Submitted"),
        ],
    )

    modal = ProjectSelectModal(include_all=True)

    assert [item.display_name for item in modal.all_items] == [
        "[*] ALL",
        "[P] home",
        "[P] valid",
        "[C] valid_active [Ready]",
    ]
