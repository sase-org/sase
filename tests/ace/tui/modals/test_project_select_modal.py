"""Tests for TUI project selection data loading."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App
from textual.widgets import OptionList, Static

from sase.ace.patch import Patch
from sase.ace.tui.modals.project_discovery import (
    is_launchable_project,
    list_launchable_projects,
)
from sase.ace.tui.modals.project_select_modal import (
    _ProjectSelectData,
    ProjectSelectModal,
    ProjectSelectResult,
)
from sase.project_display_names import ProjectDisplayProjection, ProjectDisplaySnapshot
from tests._project_display_case import ProjectDisplayCase


class _TestApp(App[ProjectSelectResult | None]):
    pass


def _static_text(modal: ProjectSelectModal, selector: str) -> str:
    return str(modal.query_one(selector, Static).render())


def _data(
    *,
    projects: tuple[tuple[str, str], ...] = (("home", "home"), ("valid", "valid")),
    patches: tuple[Patch, ...] = (),
) -> _ProjectSelectData:
    snapshot = ProjectDisplaySnapshot(dict(projects))
    return _ProjectSelectData(
        projects=tuple(
            ProjectDisplayProjection(project_key=key, project_label=label)
            for key, label in projects
        ),
        patches=patches,
        project_display_snapshot=snapshot,
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


def _patch(name: str, status: str, project_name: str = "valid") -> Patch:
    return Patch(
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

    assert [(item.project_key, item.project_label) for item in projects] == [
        ("home", "home"),
        ("valid", "valid"),
    ]
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


def test_project_select_modal_loads_launchable_projects_and_active_patches() -> None:
    modal = ProjectSelectModal(
        _data(
            patches=(
                _patch("valid_active", "Ready"),
                _patch("valid_submitted", "Submitted"),
            )
        ),
        include_all=True,
    )

    assert [item.display_name for item in modal.all_items] == [
        "[*] ALL",
        "[P] home",
        "[P] valid",
        "[PR] valid_active [Ready]",
    ]


def test_project_select_modal_excludes_named_project_rows_only() -> None:
    modal = ProjectSelectModal(
        _data(
            patches=(
                _patch("home_active", "WIP", project_name="home"),
                _patch("valid_active", "Ready"),
            )
        ),
        include_all=True,
        exclude_project_names={"home"},
    )

    assert [item.display_name for item in modal.all_items] == [
        "[*] ALL",
        "[P] valid",
        "[PR] home_active [WIP]",
        "[PR] valid_active [Ready]",
    ]


async def test_filter_updates_match_count_and_highlights_first() -> None:
    modal = ProjectSelectModal(_data(patches=(_patch("valid_active", "Ready"),)))

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


async def test_empty_state_toggles_with_no_matches() -> None:
    modal = ProjectSelectModal(_data(patches=(_patch("valid_active", "Ready"),)))

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


def test_picker_separates_labels_from_canonical_identity_and_duplicates(
    project_display_case: ProjectDisplayCase,
) -> None:
    canonical_a = project_display_case.project_key
    canonical_b = "gh_other__widgets"
    modal = ProjectSelectModal(
        _data(
            projects=(
                (canonical_b, project_display_case.project_label),
                (canonical_a, project_display_case.project_label),
            ),
            patches=(
                _patch(
                    project_display_case.patch_key,
                    "Ready",
                    project_name=canonical_a,
                ),
            ),
        )
    )

    assert [item.display_name for item in modal.all_items] == [
        f"[P] {project_display_case.project_label}",
        f"[P] {project_display_case.project_label}",
        f"[PR] {project_display_case.patch_label} [Ready]",
    ]
    assert [item.project_name for item in modal.all_items[:2]] == [
        canonical_a,
        canonical_b,
    ]
    assert modal.all_items[2].project_name == canonical_a
    assert modal.all_items[2].cl_name == project_display_case.patch_key
    assert len({item.option_id for item in modal.all_items}) == 3
