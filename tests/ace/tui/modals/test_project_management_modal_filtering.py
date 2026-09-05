"""Tests for Projects sub-tab filtering, inventory counts, and entry points."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from textual.widgets import ContentSwitcher

from sase.ace.tui.modals.project_management_rendering import (
    ProjectInventoryCounts,
    column_header_text,
)
from sase.ace.tui.modals.projects_pane import (
    ProjectsPane,
    ProjectCountsLoadResult,
)
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip

from .project_management_modal_test_helpers import (
    ProjectsPaneTestApp,
    make_project_record,
)


async def test_projects_subtab_lists_true_projects_in_both_states(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = [
        make_project_record("alpha", state="enabled", vcs_kind="gh"),
        make_project_record("core", state="sibling", launchable=False),
        make_project_record("beta", state="disabled", launchable=False),
        make_project_record("gamma", state="disabled", launchable=False),
        make_project_record("junk", is_project=False),
        make_project_record("home", system_managed=True),
    ]
    list_calls: list[tuple[Path, str, bool, bool]] = []

    def list_records(
        root: Path,
        state_filter: str,
        *,
        include_home: bool,
        projects_only: bool,
    ):
        list_calls.append((root, state_filter, include_home, projects_only))
        return records

    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        list_records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.collect_project_inventory_counts",
        lambda *_args: ProjectCountsLoadResult({}),
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()

        assert list_calls == [(tmp_path, "all", False, True)]
        assert pane._active_subtab == "projects"
        assert [record.project_name for record in pane._filtered_records] == [
            "alpha",
            "beta",
            "gamma",
        ]
        summary = pane._summary_text().plain
        assert "enabled:1" in summary
        assert "disabled:2" in summary
        assert "sibling" not in summary
        assert "disabled rows" not in summary
        assert "● enabled" in pane._record_label(records[0]).plain
        assert "○ disabled" in pane._record_label(records[2]).plain

        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert pane._active_subtab == "repos"
        switcher = pane.query_one("#projects-subtab-switcher", ContentSwitcher)
        assert switcher.current == "projects-subtab-repos"

        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert pane._active_subtab == "workspaces"

        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert pane._active_subtab == "projects"

        await pilot.press("left_square_bracket")
        await pilot.pause()
        assert pane._active_subtab == "workspaces"


def test_projects_subtab_renders_new_columns_and_alias_detail(
    monkeypatch,
    tmp_path: Path,
) -> None:
    record = make_project_record(
        "gh_org__alpha",
        aliases=["bob", "docs"],
        display_name="alpha",
        vcs_kind="gh",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: [record],
    )

    pane = ProjectsPane(projects_root=tmp_path)

    header = column_header_text().plain
    assert "CUR" in header
    assert "VCS" in header
    assert "WS" in header
    assert "REPOS" in header
    assert "ALIASES" not in header
    assert "alpha (gh_org__alpha)" in pane._record_label(record).plain
    assert "gh" in pane._record_label(record).plain
    assert "Aliases:" in pane._detail_text(record).plain
    assert "bob, docs" in pane._detail_text(record).plain
    assert "A aliases" in pane._hints_text()


def test_projects_subtab_filters_by_alias(
    monkeypatch,
    tmp_path: Path,
) -> None:
    records = [
        make_project_record("alpha", aliases=["bob", "docs"]),
        make_project_record("beta", state="disabled", launchable=False),
    ]
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: records,
    )

    pane = ProjectsPane(projects_root=tmp_path)
    pane._text_filter = "docs"
    pane._apply_filters()

    assert [record.project_name for record in pane._filtered_records] == ["alpha"]


async def test_project_inventory_counts_load_off_thread_and_render(
    monkeypatch,
    tmp_path: Path,
) -> None:
    record = make_project_record("alpha", claims=2)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    counts = ProjectInventoryCounts(
        repo_count=4,
        primary_repo_count=1,
        sidecar_repo_count=2,
        linked_repo_count=1,
        workspace_count=7,
        claimed_workspace_count=2,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.collect_project_inventory_counts",
        lambda *_args: ProjectCountsLoadResult({"alpha": counts}),
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        await pilot.pause()

        assert pane._inventory_loading is False
        assert pane._inventory_counts == {"alpha": counts}
        row = pane._record_label(record).plain
        assert "7" in row
        assert "4" in row
        detail = pane._detail_text(record).plain
        assert "Repos: 4 (1 primary · 2 sidecar · 1 linked)" in detail
        assert "Workspaces: 7 (2 claimed)" in detail


async def test_projects_subtabs_are_clickable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: [make_project_record("alpha")],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.collect_project_inventory_counts",
        lambda *_args: ProjectCountsLoadResult({}),
    )

    app = ProjectsPaneTestApp(projects_root=tmp_path)
    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        strip = pane.query_one("#projects-subtabs", PanelTabStrip)
        start, _end = strip._tab_ranges["repos"]
        center_pad = max(0, (strip.size.width - strip._line_width) // 2)

        await pilot.click(strip, offset=(center_pad + start + 1, 0))
        await pilot.pause()

        assert pane._active_subtab == "repos"


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
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.collect_project_inventory_counts",
        lambda *_args: ProjectCountsLoadResult({}),
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


def test_projects_subtab_footer_has_lifecycle_and_subtab_affordances(
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
    assert "d disable" in pane._hints_text()
    assert "Ctrl+D delete" in pane._hints_text()
    assert "[ / ] sub-tab" in pane._hints_text()
    assert "i init" in pane._hints_text()
    assert "I init all" in pane._hints_text()
    assert "F force after block" not in pane._hints_text()
    assert "Ctrl+X" not in pane._hints_text()
    assert "state" not in pane._hints_text()
    assert "Tab/Shift+Tab switch tab" in pane._hints_text()
