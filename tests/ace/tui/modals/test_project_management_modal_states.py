"""Tests for Projects pane state changes."""

from __future__ import annotations

from pathlib import Path

from textual.widgets import OptionList

from sase.ace.tui.modals.projects_pane import ProjectsPane
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.main.project_handler import ProjectLifecycleBlockedError

from .project_management_modal_test_helpers import (
    ProjectsPaneTestApp,
    make_project_record,
)


async def test_project_management_modal_enable_mutates_and_reloads(
    monkeypatch,
    tmp_path: Path,
) -> None:
    states = {"alpha": "disabled"}
    calls: list[tuple[str, str, bool]] = []

    def list_records(*_args, **_kwargs):
        return [
            make_project_record(
                "alpha",
                state=states["alpha"],
                launchable=states["alpha"] == "enabled",
            )
        ]

    def set_state(
        project: str, state: str, *, force: bool = False
    ) -> ProjectRecordWire:
        calls.append((project, state, force))
        states[project] = state
        return make_project_record(project, state=state, launchable=state == "enabled")

    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.set_project_state_locked",
        set_state,
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()

        assert [record.project_name for record in pane._filtered_records] == ["alpha"]

        await pilot.press("enter")
        await pilot.pause()

        assert calls == [("alpha", "enabled", False)]
        assert pane._records[0].state == "enabled"
        assert [record.project_name for record in pane._filtered_records] == ["alpha"]
        assert pane._status_message == "alpha -> enabled"


async def test_projects_subtab_never_surfaces_or_enables_sibling_record(
    monkeypatch,
    tmp_path: Path,
) -> None:
    states = {"core": "sibling"}
    calls: list[tuple[str, str, bool]] = []

    def list_records(*_args, **_kwargs):
        return [
            make_project_record(
                "core",
                state=states["core"],
                launchable=states["core"] == "enabled",
            )
        ]

    def set_state(
        project: str, state: str, *, force: bool = False
    ) -> ProjectRecordWire:
        calls.append((project, state, force))
        states[project] = state
        return make_project_record(project, state=state, launchable=state == "enabled")

    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.set_project_state_locked",
        set_state,
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()

        assert pane._records == []
        assert pane._filtered_records == []

        await pilot.press("enter")
        await pilot.pause()

        assert calls == []
        assert states == {"core": "sibling"}


async def test_project_management_modal_force_disable_after_block(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state = {"alpha": "enabled"}
    calls: list[tuple[str, str, bool]] = []

    def list_records(*_args, **_kwargs):
        return [
            make_project_record(
                "alpha",
                state=state["alpha"],
                claims=1,
                launchable=state["alpha"] == "enabled",
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
        "sase.ace.tui.modals.projects_pane.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.set_project_state_locked",
        set_state,
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()

        await pilot.press("d")
        await pilot.pause()
        assert pane._pending_force == (("alpha",), "disabled")
        assert "Blocked:" in pane._status_message

        await pilot.press("F")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert calls == [
            ("alpha", "disabled", False),
            ("alpha", "disabled", True),
        ]
        assert pane._pending_force is None
        assert pane._records[0].state == "disabled"
        assert [record.project_name for record in pane._filtered_records] == ["alpha"]


async def test_project_management_modal_bulk_state_targets_marked_projects(
    monkeypatch,
    tmp_path: Path,
) -> None:
    states = {"alpha": "enabled", "beta": "enabled", "gamma": "enabled"}
    calls: list[tuple[str, str, bool]] = []

    def list_records(*_args, **_kwargs):
        return [
            make_project_record(name, state=state, launchable=state == "enabled")
            for name, state in states.items()
        ]

    def set_state(
        project: str, state: str, *, force: bool = False
    ) -> ProjectRecordWire:
        calls.append((project, state, force))
        states[project] = state
        return make_project_record(project, state=state, launchable=state == "enabled")

    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.set_project_state_locked",
        set_state,
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()

        option_list = pane.query_one("#projects-list", OptionList)
        option_list.highlighted = 1
        await pilot.press("m")
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()

        assert option_list.highlighted == 0
        assert pane._marked_projects == {"beta", "gamma"}

        await pilot.press("d")
        await pilot.pause()

        assert calls == [
            ("beta", "disabled", False),
            ("gamma", "disabled", False),
        ]
        assert pane._marked_projects == set()
        assert states == {
            "alpha": "enabled",
            "beta": "disabled",
            "gamma": "disabled",
        }


async def test_project_management_modal_bulk_state_preserves_blocked_and_failed_marks_then_forces(
    monkeypatch,
    tmp_path: Path,
) -> None:
    states = {"alpha": "enabled", "beta": "enabled", "gamma": "enabled"}
    calls: list[tuple[str, str, bool]] = []

    def list_records(*_args, **_kwargs):
        return [
            make_project_record(name, state=state, launchable=state == "enabled")
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
        return make_project_record(project, state=state, launchable=state == "enabled")

    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.set_project_state_locked",
        set_state,
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()

        await pilot.press("m")
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()
        await pilot.press("m")
        await pilot.pause()

        await pilot.press("d")
        await pilot.pause()

        assert calls == [
            ("alpha", "disabled", False),
            ("beta", "disabled", False),
            ("gamma", "disabled", False),
        ]
        assert pane._marked_projects == {"beta", "gamma"}
        assert pane._pending_force == (("beta",), "disabled")
        assert states["alpha"] == "disabled"
        assert states["beta"] == "enabled"

        await pilot.press("F")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert calls[-1] == ("beta", "disabled", True)
        assert pane._marked_projects == {"gamma"}
        assert pane._pending_force is None
        assert states["beta"] == "disabled"
