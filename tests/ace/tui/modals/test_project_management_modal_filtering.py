"""Tests for project management modal filtering and entry points."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

from sase.ace.tui.modals.project_management_modal import (
    _DEFAULT_STATE_FILTER,
    ProjectManagementModal,
)
from sase.ace.tui.modals.project_management_rendering import column_header_text

from .project_management_modal_test_helpers import (
    ProjectManagementTestApp,
    make_project_record,
)


async def test_project_management_modal_filters_states(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = [
        make_project_record("alpha", state="active"),
        make_project_record("core", state="sibling", launchable=False),
        make_project_record("beta", state="inactive", launchable=False),
        make_project_record("gamma", state="inactive", launchable=False),
        make_project_record("home", state="active", system_managed=True),
    ]
    list_calls: list[tuple[Path, str, bool]] = []

    def list_records(root: Path, state_filter: str, *, include_home: bool):
        list_calls.append((root, state_filter, include_home))
        return records

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert list_calls == [(tmp_path, "all", False)]
        assert modal._state_filter == _DEFAULT_STATE_FILTER
        assert modal._show_inactive_projects is False
        assert [r.project_name for r in modal._filtered_records] == ["alpha"]
        summary = modal._summary_text().plain
        assert "all:4 active:1 sibling:1 inactive:2" in summary
        assert "inactive rows:hidden" in summary
        tabs = modal._state_tabs_text().plain
        assert "ACTIVE" in tabs
        assert "sibling" in tabs
        assert "inactive" in tabs
        assert modal._record_label(records[2]).plain.startswith("!")

        await pilot.press("ctrl+x")
        await pilot.pause()
        assert modal._show_inactive_projects is True
        assert [r.project_name for r in modal._filtered_records] == [
            "alpha",
            "beta",
            "gamma",
        ]
        assert "inactive rows:visible" in modal._summary_text().plain
        assert "Ctrl+X hide inactive" in modal._footer_text()

        await pilot.press("ctrl+x")
        await pilot.pause()
        assert modal._show_inactive_projects is False
        assert [r.project_name for r in modal._filtered_records] == ["alpha"]
        assert "inactive rows:hidden" in modal._summary_text().plain

        modal._text_filter = "beta"
        modal._apply_filters()
        assert modal._filtered_records == []

        modal._text_filter = ""
        modal._apply_filters()

        await pilot.press("tab")
        await pilot.pause()
        assert modal._state_filter == "sibling"
        assert [r.project_name for r in modal._filtered_records] == ["core"]

        await pilot.press("tab")
        await pilot.pause()
        assert modal._state_filter == "inactive"
        assert [r.project_name for r in modal._filtered_records] == [
            "beta",
            "gamma",
        ]

        await pilot.press("tab")
        await pilot.pause()
        assert modal._state_filter == "all"
        assert [r.project_name for r in modal._filtered_records] == [
            "alpha",
            "core",
            "beta",
            "gamma",
        ]

        await pilot.press("tab")
        await pilot.pause()
        assert modal._state_filter == "active"
        assert [r.project_name for r in modal._filtered_records] == ["alpha"]

        await pilot.press("shift+tab")
        await pilot.pause()
        assert modal._state_filter == "all"
        assert [r.project_name for r in modal._filtered_records] == [
            "alpha",
            "core",
            "beta",
            "gamma",
        ]

        await pilot.press("shift+tab")
        await pilot.pause()
        assert modal._state_filter == "inactive"
        assert [r.project_name for r in modal._filtered_records] == [
            "beta",
            "gamma",
        ]

        await pilot.press("shift+tab")
        await pilot.pause()
        assert modal._state_filter == "sibling"
        assert [r.project_name for r in modal._filtered_records] == ["core"]


def test_project_management_modal_renders_alias_affordances(
    monkeypatch,
    tmp_path: Path,
) -> None:
    record = make_project_record("alpha", aliases=["bob", "docs"])
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: [record],
    )

    modal = ProjectManagementModal(projects_root=tmp_path)

    assert "ALIASES" in column_header_text().plain
    assert "bob, docs" in modal._record_label(record).plain
    assert "Aliases:" in modal._detail_text(record).plain
    assert "bob, docs" in modal._detail_text(record).plain
    assert "A aliases" in modal._footer_text()


def test_project_management_modal_filters_by_alias(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = [
        make_project_record("alpha", aliases=["bob", "docs"]),
        make_project_record("beta"),
    ]
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: records,
    )

    modal = ProjectManagementModal(projects_root=tmp_path)
    modal._text_filter = "docs"
    modal._apply_filters()

    assert [record.project_name for record in modal._filtered_records] == ["alpha"]


async def test_project_management_reload_preserves_load_failure_status(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = 0

    def list_records(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [make_project_record("alpha")]
        raise RuntimeError("disk unavailable")

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()
        monkeypatch.setattr(modal, "notify", MagicMock())

        await pilot.press("R")
        await pilot.pause()

        assert modal._status_message == "Load failed: disk unavailable"
        assert modal._records == []
        assert modal._filtered_records == []
        modal.notify.assert_called_once_with(
            "Load failed: disk unavailable",
            severity="error",
        )


def test_project_management_modal_footer_includes_delete_affordance(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: [],
    )
    modal = ProjectManagementModal(projects_root=tmp_path)

    assert "e edit" in modal._footer_text()
    assert "A aliases" in modal._footer_text()
    assert "d deactivate" in modal._footer_text()
    assert "Ctrl+D delete" in modal._footer_text()
    assert "Ctrl+X show inactive" in modal._footer_text()
    assert "Tab/Shift+Tab state" in modal._footer_text()


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
