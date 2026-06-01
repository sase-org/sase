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
    archived_workspace = tmp_path / "archived-workspace"
    no_provider_workspace = tmp_path / "no-provider-workspace"
    home_workspace = tmp_path / "home-workspace"
    for workspace in (
        valid_workspace,
        archived_workspace,
        no_provider_workspace,
        home_workspace,
    ):
        workspace.mkdir()

    _write_project(projects_dir, "valid", valid_workspace)
    _write_project(projects_dir, "archived", archived_workspace, state="archived")
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

    assert projects == ["valid"]
    assert is_launchable_project("valid", projects_dir) is True
    assert is_launchable_project("archived", projects_dir) is False
    assert is_launchable_project("stale", projects_dir) is False
    assert is_launchable_project("home", projects_dir) is False


def test_project_select_modal_loads_launchable_projects_and_active_changespecs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_select_modal.list_launchable_projects",
        lambda: ["valid"],
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
        "[H] ~ (home directory)",
        "[P] valid",
        "[C] valid_active [Ready]",
    ]
