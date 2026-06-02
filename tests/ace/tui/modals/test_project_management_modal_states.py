"""Tests for project management modal state changes."""

from __future__ import annotations

from pathlib import Path

from textual.widgets import OptionList

from sase.ace.tui.modals.project_management_modal import ProjectManagementModal
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.main.project_handler import ProjectLifecycleBlockedError

from .project_management_modal_test_helpers import (
    ProjectManagementTestApp,
    make_project_record,
)


async def test_project_management_modal_activate_mutates_and_reloads(
    monkeypatch,
    tmp_path: Path,
) -> None:
    states = {"alpha": "archived"}
    calls: list[tuple[str, str, bool]] = []

    def list_records(*_args, **_kwargs):
        return [
            make_project_record(
                "alpha", state=states["alpha"], launchable=states["alpha"] == "active"
            )
        ]

    def set_state(
        project: str, state: str, *, force: bool = False
    ) -> ProjectRecordWire:
        calls.append((project, state, force))
        states[project] = state
        return make_project_record(project, state=state, launchable=state == "active")

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.set_project_state_locked",
        set_state,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("tab")
        await pilot.pause()
        assert modal._state_filter == "archived"
        assert [record.project_name for record in modal._filtered_records] == ["alpha"]

        await pilot.press("enter")
        await pilot.pause()

        assert calls == [("alpha", "active", False)]
        assert modal._records[0].state == "active"
        assert modal._filtered_records == []
        assert modal._status_message == "alpha -> active"


async def test_project_management_modal_force_archive_after_block(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state = {"alpha": "active"}
    calls: list[tuple[str, str, bool]] = []

    def list_records(*_args, **_kwargs):
        return [
            make_project_record(
                "alpha",
                state=state["alpha"],
                claims=1,
                launchable=state["alpha"] == "active",
            )
        ]

    def set_state(
        project: str, target: str, *, force: bool = False
    ) -> ProjectRecordWire:
        calls.append((project, target, force))
        if not force:
            raise ProjectLifecycleBlockedError(
                project,
                target,
                [],
                [tmp_path / "running.json"],
            )
        state[project] = target
        return make_project_record(project, state=target, claims=1, launchable=False)

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.set_project_state_locked",
        set_state,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("r")
        await pilot.pause()
        assert modal._pending_force == (("alpha",), "archived")
        assert "Blocked:" in modal._status_message

        await pilot.press("F")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert calls == [
            ("alpha", "archived", False),
            ("alpha", "archived", True),
        ]
        assert modal._pending_force is None
        assert modal._records[0].state == "archived"
        assert modal._filtered_records == []


async def test_project_management_modal_bulk_state_targets_marked_projects(
    monkeypatch,
    tmp_path: Path,
) -> None:
    states = {"alpha": "active", "beta": "active", "gamma": "active"}
    calls: list[tuple[str, str, bool]] = []

    def list_records(*_args, **_kwargs):
        return [
            make_project_record(name, state=state, launchable=state == "active")
            for name, state in states.items()
        ]

    def set_state(
        project: str, state: str, *, force: bool = False
    ) -> ProjectRecordWire:
        calls.append((project, state, force))
        states[project] = state
        return make_project_record(project, state=state, launchable=state == "active")

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.set_project_state_locked",
        set_state,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#project-management-list", OptionList)
        option_list.highlighted = 1
        await pilot.press("m")
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()

        assert option_list.highlighted == 0
        assert modal._marked_projects == {"beta", "gamma"}

        await pilot.press("r")
        await pilot.pause()

        assert calls == [
            ("beta", "archived", False),
            ("gamma", "archived", False),
        ]
        assert modal._marked_projects == set()
        assert states == {
            "alpha": "active",
            "beta": "archived",
            "gamma": "archived",
        }


async def test_project_management_modal_bulk_state_preserves_blocked_and_failed_marks_then_forces(
    monkeypatch,
    tmp_path: Path,
) -> None:
    states = {"alpha": "active", "beta": "active", "gamma": "active"}
    calls: list[tuple[str, str, bool]] = []

    def list_records(*_args, **_kwargs):
        return [
            make_project_record(name, state=state, launchable=state == "active")
            for name, state in states.items()
        ]

    def set_state(
        project: str, state: str, *, force: bool = False
    ) -> ProjectRecordWire:
        calls.append((project, state, force))
        if project == "beta" and not force:
            raise ProjectLifecycleBlockedError(
                project,
                state,
                [],
                [tmp_path / "running.json"],
            )
        if project == "gamma":
            raise RuntimeError("boom")
        states[project] = state
        return make_project_record(project, state=state, launchable=state == "active")

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.set_project_state_locked",
        set_state,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("m")
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()

        await pilot.press("r")
        await pilot.pause()

        assert calls == [
            ("alpha", "archived", False),
            ("beta", "archived", False),
            ("gamma", "archived", False),
        ]
        assert modal._marked_projects == {"beta", "gamma"}
        assert modal._pending_force == (("beta",), "archived")
        assert states["alpha"] == "archived"
        assert states["beta"] == "active"

        await pilot.press("F")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert calls[-1] == ("beta", "archived", True)
        assert modal._marked_projects == {"gamma"}
        assert modal._pending_force is None
        assert states["beta"] == "archived"
