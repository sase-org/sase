"""Tests for Projects pane deletion behavior."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.projects_pane import ProjectsPane
from sase.main.project_handler import ProjectLifecycleBlockedError

from .project_management_modal_test_helpers import (
    ProjectsPaneTestApp,
    make_project_record,
)


async def test_project_management_modal_ctrl_d_opens_delete_confirmation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: [make_project_record("alpha")],
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
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
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: [make_project_record("alpha")],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.delete_project_locked",
        lambda project, **_kwargs: calls.append(project),
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        base_screen = pilot.app.screen

        await pilot.press("ctrl+d")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        assert pilot.app.screen is base_screen
        assert calls == []
        assert pane._status_message == "Delete cancelled"


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
        "sase.ace.tui.modals.projects_pane.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.delete_project_locked",
        delete_project,
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()

        pilot.app._schedule_patches_async_refresh = MagicMock()
        pilot.app._refresh_current_tab = MagicMock()

        await pilot.press("ctrl+d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert calls == [("alpha", tmp_path)]
        assert [r.project_name for r in pane._filtered_records] == ["beta"]
        assert pane._status_message == "Deleted alpha"
        pilot.app._schedule_patches_async_refresh.assert_called_once_with()
        pilot.app._refresh_current_tab.assert_called_once_with()


async def test_projects_subtab_hides_defaulted_missing_spec_record(
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
        is_project=False,
    )

    def list_records(*_args, **_kwargs):
        return [record] if project_dir.exists() else []

    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        list_records,
    )
    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()

        assert pane._records == []
        assert pane._filtered_records == []
        assert project_dir.exists()


async def test_project_management_modal_delete_blocked_keeps_row_visible(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
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
        "sase.ace.tui.modals.projects_pane.delete_project_locked",
        delete_project,
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        base_screen = pilot.app.screen

        await pilot.press("ctrl+d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert pilot.app.screen is base_screen
        assert [r.project_name for r in pane._filtered_records] == ["alpha"]
        assert "Blocked:" in pane._status_message
        assert "live artifact marker" in pane._status_message


async def test_project_management_modal_bulk_delete_cancel_preserves_marks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: [
            make_project_record("alpha"),
            make_project_record("beta"),
        ],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.delete_project_locked",
        lambda project, **_kwargs: calls.append(project),
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        base_screen = pilot.app.screen

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

        assert pilot.app.screen is base_screen
        assert calls == []
        assert pane._marked_projects == {"alpha", "beta"}
        assert pane._status_message == "Delete cancelled"


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
        "sase.ace.tui.modals.projects_pane.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.delete_project_locked",
        delete_project,
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()

        pilot.app._schedule_patches_async_refresh = MagicMock()
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
        assert [record.project_name for record in pane._filtered_records] == [
            "beta",
            "gamma",
        ]
        assert pane._marked_projects == {"beta", "gamma"}
        assert "1 deleted" in pane._status_message
        assert "1 blocked" in pane._status_message
        assert "1 failed" in pane._status_message
        pilot.app._schedule_patches_async_refresh.assert_called_once_with()
        pilot.app._refresh_current_tab.assert_called_once_with()
