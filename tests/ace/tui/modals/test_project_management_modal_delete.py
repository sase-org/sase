"""Tests for project management modal deletion behavior."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.project_management_modal import ProjectManagementModal
from sase.main.project_handler import ProjectLifecycleBlockedError

from .project_management_modal_test_helpers import (
    ProjectManagementTestApp,
    make_project_record,
)


async def test_project_management_modal_ctrl_d_opens_delete_confirmation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: [make_project_record("alpha")],
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("ctrl+d")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ConfirmActionModal)
        confirm = cast(ConfirmActionModal, pilot.app.screen)
        assert "alpha" in confirm._message
        assert str(tmp_path / "alpha") in confirm._message
        assert "workspace checkout is not deleted" in confirm._message


async def test_project_management_modal_delete_cancel_does_not_call_helper(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: [make_project_record("alpha")],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.delete_project_locked",
        lambda project, **_kwargs: calls.append(project),
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("ctrl+d")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert calls == []
        assert modal._status_message == "Delete cancelled"


async def test_project_management_modal_delete_confirm_reloads_and_removes_row(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = {
        "alpha": make_project_record("alpha"),
        "beta": make_project_record("beta"),
    }
    calls: list[tuple[str, Path | None]] = []

    def list_records(*_args, **_kwargs):
        return list(records.values())

    def delete_project(project: str, *, projects_root: Path | None = None) -> Path:
        calls.append((project, projects_root))
        del records[project]
        return tmp_path / project

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.delete_project_locked",
        delete_project,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        pilot.app._schedule_changespecs_async_refresh = MagicMock()
        pilot.app._refresh_current_tab = MagicMock()

        await pilot.press("ctrl+d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert calls == [("alpha", tmp_path)]
        assert [r.project_name for r in modal._filtered_records] == ["beta"]
        assert modal._status_message == "Deleted alpha"
        pilot.app._schedule_changespecs_async_refresh.assert_called_once_with()
        pilot.app._refresh_current_tab.assert_called_once_with()


async def test_project_management_modal_deletes_defaulted_missing_spec_record(
    monkeypatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "alpha"
    project_dir.mkdir()
    (project_dir / "sase.yml").write_text("xprompts: []\n", encoding="utf-8")
    record = make_project_record(
        "alpha",
        explicit=False,
        launchable=False,
        warnings=[f"active ProjectSpec file not found: {project_dir / 'alpha.sase'}"],
        project_dir=str(project_dir),
        project_file=str(project_dir / "alpha.sase"),
    )

    def list_records(*_args, **_kwargs):
        return [record] if project_dir.exists() else []

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.main.project_handler.list_project_records",
        list_records,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("ctrl+d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert not project_dir.exists()
        assert modal._filtered_records == []
        assert modal._status_message == "Deleted alpha"
        assert "was not found" not in modal._status_message


async def test_project_management_modal_delete_blocked_keeps_row_visible(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: [make_project_record("alpha")],
    )

    def delete_project(project: str, *, projects_root: Path | None = None) -> Path:
        raise ProjectLifecycleBlockedError(
            project,
            "delete",
            [],
            [tmp_path / "running.json"],
        )

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.delete_project_locked",
        delete_project,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("ctrl+d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert [r.project_name for r in modal._filtered_records] == ["alpha"]
        assert "Blocked:" in modal._status_message
        assert "live artifact marker" in modal._status_message


async def test_project_management_modal_bulk_delete_cancel_preserves_marks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: [
            make_project_record("alpha"),
            make_project_record("beta"),
        ],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.delete_project_locked",
        lambda project, **_kwargs: calls.append(project),
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("m")
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()

        await pilot.press("ctrl+d")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ConfirmActionModal)
        confirm = cast(ConfirmActionModal, pilot.app.screen)
        assert "2 marked projects" in confirm._message
        assert "alpha" in confirm._message
        assert "beta" in confirm._message

        await pilot.press("n")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert calls == []
        assert modal._marked_projects == {"alpha", "beta"}
        assert modal._status_message == "Delete cancelled"


async def test_project_management_modal_bulk_delete_deletes_once_and_preserves_failed_marks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = {
        "alpha": make_project_record("alpha"),
        "beta": make_project_record("beta"),
        "gamma": make_project_record("gamma"),
    }
    calls: list[tuple[str, Path | None]] = []

    def list_records(*_args, **_kwargs):
        return list(records.values())

    def delete_project(project: str, *, projects_root: Path | None = None) -> Path:
        calls.append((project, projects_root))
        if project == "beta":
            raise ProjectLifecycleBlockedError(
                project,
                "delete",
                [],
                [tmp_path / "running.json"],
            )
        if project == "gamma":
            raise RuntimeError("boom")
        del records[project]
        return tmp_path / project

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.delete_project_locked",
        delete_project,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        pilot.app._schedule_changespecs_async_refresh = MagicMock()
        pilot.app._refresh_current_tab = MagicMock()

        await pilot.press("m")
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()

        await pilot.press("ctrl+d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert calls == [
            ("alpha", tmp_path),
            ("beta", tmp_path),
            ("gamma", tmp_path),
        ]
        assert [record.project_name for record in modal._filtered_records] == [
            "beta",
            "gamma",
        ]
        assert modal._marked_projects == {"beta", "gamma"}
        assert "1 deleted" in modal._status_message
        assert "1 blocked" in modal._status_message
        assert "1 failed" in modal._status_message
        pilot.app._schedule_changespecs_async_refresh.assert_called_once_with()
        pilot.app._refresh_current_tab.assert_called_once_with()
