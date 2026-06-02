"""Tests for project management modal filtering and entry points."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

from sase.ace.tui.modals.project_management_modal import ProjectManagementModal

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
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: records,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
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
