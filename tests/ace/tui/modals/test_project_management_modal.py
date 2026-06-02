"""Tests for the ace project lifecycle management modal."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.project_management_modal import ProjectManagementModal
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.main.project_handler import ProjectLifecycleBlockedError


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _record(
    name: str,
    *,
    state: str = "active",
    explicit: bool = True,
    claims: int = 0,
    launchable: bool = True,
    warnings: list[str] | None = None,
    system_managed: bool = False,
    project_dir: str | None = None,
    project_file: str | None = None,
) -> ProjectRecordWire:
    project_dir_text = project_dir or f"/tmp/projects/{name}"
    project_file_text = project_file or f"{project_dir_text}/{name}.sase"
    return ProjectRecordWire(
        schema_version=1,
        project_name=name,
        project_dir=project_dir_text,
        project_file=project_file_text,
        archive_file=None,
        workspace_dir=f"/tmp/workspaces/{name}",
        state=state,
        state_explicit=explicit,
        system_managed=system_managed,
        active_claim_count=claims,
        launchable=launchable,
        warnings=warnings or [],
        parse_warnings=[],
    )


async def test_project_management_modal_filters_states(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = [
        _record("alpha", state="active"),
        _record("beta", state="archived", launchable=False),
        _record("gamma", state="closed", launchable=False),
        _record("home", state="active", system_managed=True),
    ]
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: records,
    )

    async with _TestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert [r.project_name for r in modal._filtered_records] == [
            "alpha",
            "beta",
            "gamma",
        ]

        await pilot.press("tab")
        await pilot.pause()
        assert modal._state_filter == "active"
        assert [r.project_name for r in modal._filtered_records] == ["alpha"]

        await pilot.press("tab")
        await pilot.pause()
        assert modal._state_filter == "archived"
        assert [r.project_name for r in modal._filtered_records] == ["beta"]


async def test_project_management_modal_activate_mutates_and_reloads(
    monkeypatch,
    tmp_path: Path,
) -> None:
    states = {"alpha": "archived"}
    calls: list[tuple[str, str, bool]] = []

    def list_records(*_args, **_kwargs):
        return [
            _record(
                "alpha", state=states["alpha"], launchable=states["alpha"] == "active"
            )
        ]

    def set_state(
        project: str, state: str, *, force: bool = False
    ) -> ProjectRecordWire:
        calls.append((project, state, force))
        states[project] = state
        return _record(project, state=state, launchable=state == "active")

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.set_project_state_locked",
        set_state,
    )

    async with _TestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert calls == [("alpha", "active", False)]
        assert modal._filtered_records[0].state == "active"
        assert modal._status_message == "alpha -> active"


async def test_project_management_modal_force_archive_after_block(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state = {"alpha": "active"}
    calls: list[tuple[str, str, bool]] = []

    def list_records(*_args, **_kwargs):
        return [
            _record(
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
        return _record(project, state=target, claims=1, launchable=False)

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.set_project_state_locked",
        set_state,
    )

    async with _TestApp().run_test() as pilot:
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
        assert modal._filtered_records[0].state == "archived"


async def test_project_management_modal_mark_toggles_advances_and_updates_text(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: [
            _record("alpha"),
            _record("beta"),
            _record("gamma"),
        ],
    )

    async with _TestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("m")
        await pilot.pause()

        option_list = modal.query_one("#project-management-list", OptionList)
        assert modal._marked_projects == {"alpha"}
        assert option_list.highlighted == 1
        assert "[✓] alpha" in option_list.get_option_at_index(0).prompt.plain
        assert "marked:1" in modal._summary_text().plain
        assert "marked:1" in modal._footer_text()


async def test_project_management_modal_clear_marks_restores_row_labels(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: [_record("alpha"), _record("beta")],
    )

    async with _TestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("m")
        await pilot.pause()
        await pilot.press("u")
        await pilot.pause()

        option_list = modal.query_one("#project-management-list", OptionList)
        assert modal._marked_projects == set()
        assert "[✓]" not in option_list.get_option_at_index(0).prompt.plain
        assert "[✓]" not in option_list.get_option_at_index(1).prompt.plain
        assert modal._status_message == "Cleared 1 mark(s)"


async def test_project_management_modal_marks_survive_filters_and_prune_on_reload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = {
        "alpha": _record("alpha"),
        "beta": _record("beta", state="archived", launchable=False),
        "gamma": _record("gamma", state="closed", launchable=False),
    }

    def list_records(*_args, **_kwargs):
        return list(records.values())

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )

    async with _TestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#project-management-list", OptionList)
        option_list.highlighted = 1
        await pilot.press("m")
        await pilot.pause()

        assert modal._marked_projects == {"beta"}

        modal._text_filter = "alpha"
        modal._apply_filters()
        modal._refresh_options()
        assert [record.project_name for record in modal._filtered_records] == ["alpha"]
        assert modal._marked_projects == {"beta"}

        await pilot.press("tab")
        await pilot.pause()
        assert modal._state_filter == "active"
        assert modal._marked_projects == {"beta"}

        del records["beta"]
        await pilot.press("R")
        await pilot.pause()

        assert modal._marked_projects == set()
        assert "marked:0" in modal._summary_text().plain


async def test_project_management_modal_bulk_state_targets_marked_projects(
    monkeypatch,
    tmp_path: Path,
) -> None:
    states = {"alpha": "active", "beta": "active", "gamma": "active"}
    calls: list[tuple[str, str, bool]] = []

    def list_records(*_args, **_kwargs):
        return [
            _record(name, state=state, launchable=state == "active")
            for name, state in states.items()
        ]

    def set_state(
        project: str, state: str, *, force: bool = False
    ) -> ProjectRecordWire:
        calls.append((project, state, force))
        states[project] = state
        return _record(project, state=state, launchable=state == "active")

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.set_project_state_locked",
        set_state,
    )

    async with _TestApp().run_test() as pilot:
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
            _record(name, state=state, launchable=state == "active")
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
        return _record(project, state=state, launchable=state == "active")

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.set_project_state_locked",
        set_state,
    )

    async with _TestApp().run_test() as pilot:
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


async def test_project_management_modal_ctrl_d_opens_delete_confirmation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: [_record("alpha")],
    )

    async with _TestApp().run_test() as pilot:
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
        lambda *_args, **_kwargs: [_record("alpha")],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.delete_project_locked",
        lambda project, **_kwargs: calls.append(project),
    )

    async with _TestApp().run_test() as pilot:
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
        "alpha": _record("alpha"),
        "beta": _record("beta"),
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

    async with _TestApp().run_test() as pilot:
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
    record = _record(
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

    async with _TestApp().run_test() as pilot:
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
        lambda *_args, **_kwargs: [_record("alpha")],
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

    async with _TestApp().run_test() as pilot:
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
        lambda *_args, **_kwargs: [_record("alpha"), _record("beta")],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.delete_project_locked",
        lambda project, **_kwargs: calls.append(project),
    )

    async with _TestApp().run_test() as pilot:
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
        "alpha": _record("alpha"),
        "beta": _record("beta"),
        "gamma": _record("gamma"),
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

    async with _TestApp().run_test() as pilot:
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


def test_project_management_modal_footer_includes_delete_affordance(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: [],
    )
    modal = ProjectManagementModal(projects_root=tmp_path)

    assert "Ctrl+D delete" in modal._footer_text()


def test_leader_handler_dispatches_project_management_on_all_tabs() -> None:
    from sase.ace.tui.actions.agent_workflow._leader_mode import LeaderModeMixin
    from sase.ace.tui.keymaps import load_keymap_registry

    for tab in ("changespecs", "agents", "axe"):
        mixin = MagicMock()
        mixin._keymap_registry = load_keymap_registry({})
        mixin.current_tab = tab
        mixin.marked_indices = set()
        mixin._leader_mode_active = True

        handled = LeaderModeMixin._handle_leader_key(cast(LeaderModeMixin, mixin), "p")

        assert handled is True
        mixin.action_open_project_management_panel.assert_called_once()
