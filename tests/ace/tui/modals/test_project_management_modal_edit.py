"""Tests for project management modal ProjectSpec editing."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest
from textual.widgets import Input, OptionList

from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.project_alias_editor_modal import ProjectAliasEditorModal
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


async def test_project_management_modal_alias_editor_updates_selected_project(
    monkeypatch,
    tmp_path: Path,
) -> None:
    aliases_by_project = {"alpha": ["old"], "beta": []}
    set_calls: list[tuple[str, list[str], Path | None]] = []

    def record_for(project: str):
        return make_project_record(project, aliases=aliases_by_project[project])

    def list_records(*_args, **_kwargs):
        records = [record_for("alpha"), record_for("beta")]
        if aliases_by_project["alpha"] == ["old"]:
            return records
        return [records[1], records[0]]

    def set_aliases(
        project: str,
        aliases: list[str],
        *,
        projects_root: Path | None = None,
    ):
        set_calls.append((project, aliases, projects_root))
        aliases_by_project[project] = list(aliases)
        return record_for(project)

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.set_project_aliases_locked",
        set_aliases,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()
        pilot.app._schedule_changespecs_async_refresh = MagicMock()
        pilot.app._schedule_agents_async_refresh = MagicMock()
        pilot.app._schedule_axe_async_refresh = MagicMock()
        pilot.app._refresh_current_tab = MagicMock()
        monkeypatch.setattr(modal, "notify", MagicMock())

        await pilot.press("A")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ProjectAliasEditorModal)
        editor = cast(ProjectAliasEditorModal, pilot.app.screen)
        editor.query_one("#project-alias-input", Input).value = "new, docs"
        await pilot.press("enter")
        await pilot.pause()

        assert set_calls == [("alpha", ["docs", "new"], tmp_path)]
        assert [record.project_name for record in modal._filtered_records] == [
            "beta",
            "alpha",
        ]
        option_list = modal.query_one("#project-management-list", OptionList)
        assert option_list.highlighted == 1
        assert modal._status_message == "alpha aliases: docs, new"
        modal.notify.assert_called_once_with("Updated aliases for 'alpha'")
        pilot.app._schedule_changespecs_async_refresh.assert_called_once_with()
        pilot.app._schedule_agents_async_refresh.assert_called_once_with(
            source="project_lifecycle",
            full_history=False,
        )
        pilot.app._schedule_axe_async_refresh.assert_called_once_with()
        pilot.app._refresh_current_tab.assert_called_once_with()


async def test_project_management_modal_alias_editor_empty_input_confirms_clear(
    monkeypatch,
    tmp_path: Path,
) -> None:
    aliases = {"alpha": ["old"]}
    set_calls: list[tuple[str, list[str]]] = []

    def list_records(*_args, **_kwargs):
        return [make_project_record("alpha", aliases=aliases["alpha"])]

    def set_aliases(
        project: str,
        new_aliases: list[str],
        *,
        projects_root: Path | None = None,
    ):
        assert projects_root == tmp_path
        set_calls.append((project, new_aliases))
        aliases[project] = list(new_aliases)
        return make_project_record(project, aliases=new_aliases)

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.set_project_aliases_locked",
        set_aliases,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("A")
        await pilot.pause()
        editor = cast(ProjectAliasEditorModal, pilot.app.screen)
        editor.query_one("#project-alias-input", Input).value = ""
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ConfirmActionModal)
        assert set_calls == []

        await pilot.press("y")
        await pilot.pause()

        assert set_calls == [("alpha", [])]
        assert modal._status_message == "alpha aliases: none"


async def test_project_management_modal_alias_editor_targets_highlighted_not_marked(
    monkeypatch,
    tmp_path: Path,
) -> None:
    aliases_by_project = {"alpha": [], "beta": ["marked"]}
    set_calls: list[tuple[str, list[str]]] = []

    def list_records(*_args, **_kwargs):
        return [
            make_project_record(project, aliases=aliases_by_project[project])
            for project in ("alpha", "beta")
        ]

    def set_aliases(
        project: str,
        aliases: list[str],
        *,
        projects_root: Path | None = None,
    ):
        assert projects_root == tmp_path
        set_calls.append((project, aliases))
        aliases_by_project[project] = list(aliases)
        return make_project_record(project, aliases=aliases)

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.set_project_aliases_locked",
        set_aliases,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._marked_projects = {"beta"}
        modal._refresh_options(preferred_project="alpha")

        await pilot.press("A")
        await pilot.pause()
        editor = cast(ProjectAliasEditorModal, pilot.app.screen)
        editor.query_one("#project-alias-input", Input).value = "selected"
        await pilot.press("enter")
        await pilot.pause()

        assert set_calls == [("alpha", ["selected"])]
        assert aliases_by_project == {"alpha": ["selected"], "beta": ["marked"]}
        assert modal._marked_projects == {"beta"}


@pytest.mark.parametrize(
    ("alias_text", "error"),
    [
        ("bad alias", "invalid project alias: 'bad alias'"),
        (
            "bob",
            "project alias 'bob' is assigned to both 'beta' and 'alpha'",
        ),
    ],
)
async def test_project_management_modal_alias_editor_errors_do_not_reload(
    monkeypatch,
    tmp_path: Path,
    alias_text: str,
    error: str,
) -> None:
    list_calls = 0
    set_calls: list[tuple[str, list[str]]] = []

    def list_records(*_args, **_kwargs):
        nonlocal list_calls
        list_calls += 1
        return [make_project_record("alpha")]

    def set_aliases(
        project: str,
        aliases: list[str],
        *,
        projects_root: Path | None = None,
    ):
        assert projects_root == tmp_path
        set_calls.append((project, aliases))
        raise ValueError(error)

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.set_project_aliases_locked",
        set_aliases,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()
        monkeypatch.setattr(modal, "notify", MagicMock())

        await pilot.press("A")
        await pilot.pause()
        editor = cast(ProjectAliasEditorModal, pilot.app.screen)
        editor.query_one("#project-alias-input", Input).value = alias_text
        await pilot.press("enter")
        await pilot.pause()

        assert set_calls == [("alpha", [alias_text])]
        assert list_calls == 1
        message = f"Alias update failed for alpha: {error}"
        assert modal._status_message == message
        modal.notify.assert_called_once_with(message, severity="error")


async def test_project_management_modal_alias_editor_cancel_leaves_records_untouched(
    monkeypatch,
    tmp_path: Path,
) -> None:
    set_aliases = MagicMock()
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: [make_project_record("alpha", aliases=["old"])],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.set_project_aliases_locked",
        set_aliases,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("A")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ProjectAliasEditorModal)

        await pilot.press("escape")
        await pilot.pause()

        set_aliases.assert_not_called()
        assert modal._status_message == "Alias edit cancelled"


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
