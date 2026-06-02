"""Tests for the ace project lifecycle management modal."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

from textual.app import App, ComposeResult

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
        assert modal._pending_force == ("alpha", "archived")
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
