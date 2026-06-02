"""Tests for project management modal marking behavior."""

from __future__ import annotations

from pathlib import Path

from textual.widgets import OptionList

from sase.ace.tui.modals.project_management_modal import ProjectManagementModal

from .project_management_modal_test_helpers import (
    ProjectManagementTestApp,
    make_project_record,
)


async def test_project_management_modal_mark_toggles_advances_and_updates_text(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        lambda *_args, **_kwargs: [
            make_project_record("alpha"),
            make_project_record("beta"),
            make_project_record("gamma"),
        ],
    )

    async with ProjectManagementTestApp().run_test() as pilot:
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
        lambda *_args, **_kwargs: [
            make_project_record("alpha"),
            make_project_record("beta"),
        ],
    )

    async with ProjectManagementTestApp().run_test() as pilot:
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
        "alpha": make_project_record("alpha"),
        "beta": make_project_record("beta", state="inactive", launchable=False),
        "gamma": make_project_record("gamma", state="inactive", launchable=False),
    }

    def list_records(*_args, **_kwargs):
        return list(records.values())

    monkeypatch.setattr(
        "sase.ace.tui.modals.project_management_modal.list_project_records",
        list_records,
    )

    async with ProjectManagementTestApp().run_test() as pilot:
        modal = ProjectManagementModal(projects_root=tmp_path)
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert [record.project_name for record in modal._filtered_records] == ["alpha"]

        await pilot.press("tab")
        await pilot.pause()
        assert modal._state_filter == "inactive"
        assert [record.project_name for record in modal._filtered_records] == [
            "beta",
            "gamma",
        ]

        await pilot.press("m")
        await pilot.pause()

        assert modal._marked_projects == {"beta"}

        await pilot.press("tab")
        await pilot.pause()
        assert modal._state_filter == "all"
        assert [record.project_name for record in modal._filtered_records] == [
            "alpha",
            "beta",
            "gamma",
        ]
        assert modal._marked_projects == {"beta"}

        await pilot.press("tab")
        await pilot.pause()
        assert modal._state_filter == "active"
        assert modal._marked_projects == {"beta"}

        modal._text_filter = "alpha"
        modal._apply_filters()
        modal._refresh_options()
        assert [record.project_name for record in modal._filtered_records] == ["alpha"]
        assert modal._marked_projects == {"beta"}

        del records["beta"]
        await pilot.press("R")
        await pilot.pause()

        assert modal._marked_projects == set()
        assert "marked:0" in modal._summary_text().plain
