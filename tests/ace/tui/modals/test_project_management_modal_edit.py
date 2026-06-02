"""Tests for project management modal ProjectSpec editing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from textual.widgets import OptionList

from sase.ace.tui.modals.project_management_modal import ProjectManagementModal

from .project_management_modal_test_helpers import (
    ProjectManagementTestApp,
    make_project_record,
)


class _SuspendRecorder:
    def __init__(self) -> None:
        self.active = False
        self.enters = 0
        self.exits = 0

    def __enter__(self) -> None:
        self.enters += 1
        self.active = True

    def __exit__(self, *_exc_info: object) -> None:
        self.active = False
        self.exits += 1


async def test_project_management_modal_edit_opens_selected_project_spec(
    monkeypatch,
    tmp_path: Path,
) -> None:
    alpha_dir = tmp_path / "alpha"
    beta_dir = tmp_path / "beta"
    alpha_dir.mkdir()
    beta_dir.mkdir()
    alpha_file = alpha_dir / "custom-alpha.sase"
    alpha_file.write_text("NAME: alpha\n", encoding="utf-8")
    alpha = make_project_record(
        "alpha",
        project_dir=str(alpha_dir),
        project_file=str(alpha_file),
    )
    beta = make_project_record(
        "beta",
        project_dir=str(beta_dir),
        project_file=str(beta_dir / "beta.sase"),
    )
    list_calls = 0

    def list_records(*_args, **_kwargs):
        nonlocal list_calls
        list_calls += 1
        return [alpha, beta] if list_calls == 1 else [beta, alpha]

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setenv("EDITOR", "test-editor")
    suspend = _SuspendRecorder()
    run_calls: list[tuple[list[str], bool]] = []
    lock_file = Path(f"{alpha_file}.edit_lock")

    def run_editor(args: list[str], *, check: bool):
        run_calls.append((args, check))
        assert suspend.active is True
        assert lock_file.exists()

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_actions.subprocess.run",
        run_editor,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        monkeypatch.setattr(pilot.app, "suspend", lambda: suspend)
        pilot.app._schedule_changespecs_async_refresh = MagicMock()
        pilot.app._schedule_agents_async_refresh = MagicMock()
        pilot.app._schedule_axe_async_refresh = MagicMock()
        pilot.app._refresh_current_tab = MagicMock()

        await pilot.press("e")
        await pilot.pause()

        assert run_calls == [(["test-editor", str(alpha_file)], False)]
        assert suspend.enters == 1
        assert suspend.exits == 1
        assert not lock_file.exists()
        assert [record.project_name for record in modal._filtered_records] == [
            "beta",
            "alpha",
        ]
        option_list = modal.query_one("#project-management-list", OptionList)
        assert option_list.highlighted == 1
        assert modal._status_message == "Editor closed for alpha"
        pilot.app._schedule_changespecs_async_refresh.assert_called_once_with()
        pilot.app._schedule_agents_async_refresh.assert_called_once_with(
            source="project_lifecycle",
            full_history=False,
        )
        pilot.app._schedule_axe_async_refresh.assert_called_once_with()
        pilot.app._refresh_current_tab.assert_called_once_with()


async def test_project_management_modal_edit_no_selection_warns(
    monkeypatch,
    tmp_path: Path,
) -> None:
    run_editor = MagicMock()
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_actions.subprocess.run",
        run_editor,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()
        monkeypatch.setattr(modal, "notify", MagicMock())

        await pilot.press("e")
        await pilot.pause()

        assert modal._status_message == "No project selected"
        modal.notify.assert_called_once_with("No project selected", severity="warning")
        run_editor.assert_not_called()


async def test_project_management_modal_edit_allows_missing_spec_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "alpha"
    project_dir.mkdir()
    project_file = project_dir / "alpha.sase"
    record = make_project_record(
        "alpha",
        explicit=False,
        launchable=False,
        project_dir=str(project_dir),
        project_file=str(project_file),
    )
    run_editor = MagicMock()
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_actions.subprocess.run",
        run_editor,
    )
    monkeypatch.setenv("EDITOR", "test-editor")

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()
        monkeypatch.setattr(pilot.app, "suspend", lambda: _SuspendRecorder())

        await pilot.press("e")
        await pilot.pause()

        run_editor.assert_called_once_with(
            ["test-editor", str(project_file)],
            check=False,
        )
        assert not Path(f"{project_file}.edit_lock").exists()


async def test_project_management_modal_edit_missing_parent_does_not_create_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "missing-alpha"
    project_file = project_dir / "alpha.sase"
    record = make_project_record(
        "alpha",
        project_dir=str(project_dir),
        project_file=str(project_file),
    )
    run_editor = MagicMock()
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_actions.subprocess.run",
        run_editor,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()
        monkeypatch.setattr(modal, "notify", MagicMock())

        await pilot.press("e")
        await pilot.pause()

        assert modal._status_message == f"ProjectSpec directory missing: {project_dir}"
        modal.notify.assert_called_once_with(
            f"ProjectSpec directory missing: {project_dir}",
            severity="error",
        )
        run_editor.assert_not_called()
        assert not project_dir.exists()


async def test_project_management_modal_edit_launch_failure_releases_lock(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "alpha"
    project_dir.mkdir()
    project_file = project_dir / "alpha.sase"
    record = make_project_record(
        "alpha",
        project_dir=str(project_dir),
        project_file=str(project_file),
    )
    list_calls = 0

    def list_records(*_args, **_kwargs):
        nonlocal list_calls
        list_calls += 1
        return [record]

    lock_file = Path(f"{project_file}.edit_lock")

    def run_editor(_args: list[str], *, check: bool):
        assert check is False
        assert lock_file.exists()
        raise OSError("no editor")

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_actions.subprocess.run",
        run_editor,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()
        monkeypatch.setattr(pilot.app, "suspend", lambda: _SuspendRecorder())
        monkeypatch.setattr(modal, "notify", MagicMock())
        pilot.app._schedule_changespecs_async_refresh = MagicMock()
        pilot.app._refresh_current_tab = MagicMock()

        await pilot.press("e")
        await pilot.pause()

        assert not lock_file.exists()
        assert modal._status_message == "Editor failed for alpha: no editor"
        modal.notify.assert_called_once_with(
            "Editor failed for alpha: no editor",
            severity="error",
        )
        assert list_calls == 1
        pilot.app._schedule_changespecs_async_refresh.assert_not_called()
        pilot.app._refresh_current_tab.assert_not_called()
