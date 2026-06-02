"""Tests for project management modal filtering and entry points."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

from sase.ace.tui.modals.project_management_modal import (
    _DEFAULT_STATE_FILTER,
    ProjectManagementModal,
)

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
        make_project_record("beta", state="archived", launchable=False),
        make_project_record("gamma", state="closed", launchable=False),
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
        assert [r.project_name for r in modal._filtered_records] == ["alpha"]
        summary = modal._summary_text().plain
        assert "Filter: active" in summary
        assert "all:3 active:1 archived:1 closed:1" in summary

        modal._text_filter = "beta"
        modal._apply_filters()
        assert modal._filtered_records == []

        modal._text_filter = ""
        modal._apply_filters()

        await pilot.press("tab")
        await pilot.pause()
        assert modal._state_filter == "archived"
        assert [r.project_name for r in modal._filtered_records] == ["beta"]

        await pilot.press("tab")
        await pilot.pause()
        assert modal._state_filter == "closed"
        assert [r.project_name for r in modal._filtered_records] == ["gamma"]

        await pilot.press("tab")
        await pilot.pause()
        assert modal._state_filter == "all"
        assert [r.project_name for r in modal._filtered_records] == [
            "alpha",
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
            "beta",
            "gamma",
        ]

        await pilot.press("shift+tab")
        await pilot.pause()
        assert modal._state_filter == "closed"
        assert [r.project_name for r in modal._filtered_records] == ["gamma"]


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
    assert "Ctrl+D delete" in modal._footer_text()
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
