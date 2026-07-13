"""Tests for Projects pane filtering and entry points."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from sase.ace.tui.modals.projects_pane import (
    _DEFAULT_STATE_FILTER,
    ProjectsPane,
)
from sase.ace.tui.modals.project_management_rendering import column_header_text

from .project_management_modal_test_helpers import (
    ProjectsPaneTestApp,
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
        "sase.ace.tui.modals.projects_pane.list_project_records",
        list_records,
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()

        assert list_calls == [(tmp_path, "all", False)]
        assert pane._state_filter == _DEFAULT_STATE_FILTER
        assert pane._show_inactive_projects is False
        assert [r.project_name for r in pane._filtered_records] == ["alpha"]
        summary = pane._summary_text().plain
        assert "all:4 active:1 sibling:1 inactive:2" in summary
        assert "inactive rows:hidden" in summary
        tabs = pane._state_tabs_text().plain
        assert "ACTIVE" in tabs
        assert "sibling" in tabs
        assert "inactive" in tabs
        assert pane._record_label(records[2]).plain.startswith("!")

        await pilot.press("ctrl+x")
        await pilot.pause()
        assert pane._show_inactive_projects is True
        assert [r.project_name for r in pane._filtered_records] == [
            "alpha",
            "beta",
            "gamma",
        ]
        assert "inactive rows:visible" in pane._summary_text().plain
        assert "Ctrl+X hide inactive" in pane._hints_text()

        await pilot.press("ctrl+x")
        await pilot.pause()
        assert pane._show_inactive_projects is False
        assert [r.project_name for r in pane._filtered_records] == ["alpha"]
        assert "inactive rows:hidden" in pane._summary_text().plain

        pane._text_filter = "beta"
        pane._apply_filters()
        assert pane._filtered_records == []

        pane._text_filter = ""
        pane._apply_filters()

        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert pane._state_filter == "sibling"
        assert [r.project_name for r in pane._filtered_records] == ["core"]

        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert pane._state_filter == "inactive"
        assert [r.project_name for r in pane._filtered_records] == [
            "beta",
            "gamma",
        ]

        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert pane._state_filter == "all"
        assert [r.project_name for r in pane._filtered_records] == [
            "alpha",
            "core",
            "beta",
            "gamma",
        ]

        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert pane._state_filter == "active"
        assert [r.project_name for r in pane._filtered_records] == ["alpha"]

        await pilot.press("left_square_bracket")
        await pilot.pause()
        assert pane._state_filter == "all"
        assert [r.project_name for r in pane._filtered_records] == [
            "alpha",
            "core",
            "beta",
            "gamma",
        ]

        await pilot.press("left_square_bracket")
        await pilot.pause()
        assert pane._state_filter == "inactive"
        assert [r.project_name for r in pane._filtered_records] == [
            "beta",
            "gamma",
        ]

        await pilot.press("left_square_bracket")
        await pilot.pause()
        assert pane._state_filter == "sibling"
        assert [r.project_name for r in pane._filtered_records] == ["core"]


def test_project_management_modal_renders_alias_affordances(
    monkeypatch,
    tmp_path: Path,
) -> None:
    record = make_project_record("alpha", aliases=["bob", "docs"])
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: [record],
    )

    pane = ProjectsPane(projects_root=tmp_path)

    assert "ALIASES" in column_header_text().plain
    assert "bob, docs" in pane._record_label(record).plain
    assert "Aliases:" in pane._detail_text(record).plain
    assert "bob, docs" in pane._detail_text(record).plain
    assert "A aliases" in pane._hints_text()


def test_project_management_modal_filters_by_alias(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = [
        make_project_record("alpha", aliases=["bob", "docs"]),
        make_project_record("beta"),
    ]
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: records,
    )

    pane = ProjectsPane(projects_root=tmp_path)
    pane._text_filter = "docs"
    pane._apply_filters()

    assert [record.project_name for record in pane._filtered_records] == ["alpha"]


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
        "sase.ace.tui.modals.projects_pane.list_project_records",
        list_records,
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        monkeypatch.setattr(pane, "notify", MagicMock())

        await pilot.press("R")
        await pilot.pause()

        assert pane._status_message == "Load failed: disk unavailable"
        assert pane._records == []
        assert pane._filtered_records == []
        pane.notify.assert_called_once_with(
            "Load failed: disk unavailable",
            severity="error",
        )


def test_project_management_modal_footer_includes_delete_affordance(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: [],
    )
    pane = ProjectsPane(projects_root=tmp_path)

    assert "e edit" in pane._hints_text()
    assert "A aliases" in pane._hints_text()
    assert "d deactivate" in pane._hints_text()
    assert "Ctrl+D delete" in pane._hints_text()
    assert "Ctrl+X show inactive" in pane._hints_text()
    assert "[ / ] state" in pane._hints_text()
    assert "Tab/Shift+Tab switch tab" in pane._hints_text()
