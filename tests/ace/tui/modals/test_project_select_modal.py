"""Tests for TUI project selection data loading."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App
from textual.widgets import OptionList, Static

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.modals.project_discovery import (
    is_launchable_project,
    list_launchable_projects,
)
from sase.ace.tui.modals.project_select_modal import (
    ProjectSelectModal,
    ProjectSelectResult,
)


class _TestApp(App[ProjectSelectResult | None]):
    pass


def _static_text(modal: ProjectSelectModal, selector: str) -> str:
    return str(modal.query_one(selector, Static).render())


def _patch_loaders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_select_modal.list_launchable_projects",
        lambda: ["home", "valid"],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_select_modal.find_all_changespecs",
        lambda: [_changespec("valid_active", "Ready")],
    )


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
    disabled_workspace = tmp_path / "disabled-workspace"
    sibling_workspace = tmp_path / "sibling-workspace"
    no_provider_workspace = tmp_path / "no-provider-workspace"
    home_workspace = tmp_path / "home-workspace"
    for workspace in (
        valid_workspace,
        disabled_workspace,
        sibling_workspace,
        no_provider_workspace,
        home_workspace,
    ):
        workspace.mkdir()

    _write_project(projects_dir, "valid", valid_workspace)
    _write_project(projects_dir, "disabled", disabled_workspace, state="disabled")
    _write_project(projects_dir, "sibling", sibling_workspace, state="sibling")
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
    assert is_launchable_project("disabled", projects_dir) is False
    assert is_launchable_project("sibling", projects_dir) is False
    assert is_launchable_project("stale", projects_dir) is False
    assert is_launchable_project("home", projects_dir) is True


def test_home_project_must_be_real_enabled_and_launchable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    home_workspace = tmp_path / "home-workspace"
    disabled_home_workspace = tmp_path / "disabled-home-workspace"
    home_workspace.mkdir()
    disabled_home_workspace.mkdir()

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_discovery.detect_workflow_type",
        lambda _project_file: "git",
    )

    assert is_launchable_project("home", projects_dir) is False

    home_project_file = _write_project(projects_dir, "home", home_workspace)
    assert is_launchable_project("home", projects_dir) is True

    home_project_file.write_text(
        "PROJECT_STATE: disabled\n"
        f"WORKSPACE_DIR: {disabled_home_workspace}\n"
        "NAME: disabled_home_change\n",
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
        "[PR] valid_active [Ready]",
    ]


def test_project_select_modal_excludes_named_project_rows_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_select_modal.list_launchable_projects",
        lambda: ["home", "valid"],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_select_modal.find_all_changespecs",
        lambda: [
            _changespec("home_active", "WIP", project_name="home"),
            _changespec("valid_active", "Ready"),
        ],
    )

    modal = ProjectSelectModal(
        include_all=True,
        exclude_project_names={"home"},
    )

    assert [item.display_name for item in modal.all_items] == [
        "[*] ALL",
        "[P] valid",
        "[PR] home_active [WIP]",
        "[PR] valid_active [Ready]",
    ]


async def test_filter_updates_match_count_and_highlights_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    modal = ProjectSelectModal()

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#selection-list", OptionList)

        # Unfiltered: title reflects the full item count.
        assert "3 matches" in _static_text(modal, "#project-select-title")

        modal._apply_filter("valid")
        await pilot.pause()

        # "valid" matches the project and its PR.
        assert "2 matches" in _static_text(modal, "#project-select-title")
        assert option_list.option_count == 2
        assert option_list.highlighted == 0


async def test_empty_state_toggles_with_no_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    modal = ProjectSelectModal()

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#selection-list", OptionList)
        empty = modal.query_one("#project-select-empty", Static)

        # With matches, the list is shown and the empty-state is hidden.
        assert option_list.display is True
        assert empty.display is False

        modal._apply_filter("zzz-no-such-thing")
        await pilot.pause()

        # No matches: empty-state visible, list hidden, query echoed back.
        assert option_list.display is False
        assert empty.display is True
        assert "0 matches" in _static_text(modal, "#project-select-title")
        empty_text = _static_text(modal, "#project-select-empty")
        assert "zzz-no-such-thing" in empty_text
        assert "custom name" in empty_text
