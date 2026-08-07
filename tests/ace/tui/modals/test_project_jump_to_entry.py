"""Apostrophe entry-jump behavior across the three Projects sub-tabs."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import OptionList

from sase.ace.tui.modals.project_inventory_panes import (
    RepoInventoryPane,
    WorkspaceInventoryPane,
)
from sase.ace.tui.modals.projects_pane import (
    ProjectCountsLoadResult,
    ProjectsPane,
)
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.repo_inventory import RepoInventory, RepoRecord
from sase.workspace_provider.inventory import (
    WorkspaceInventory,
    WorkspaceInventoryRecord,
)

from .project_management_modal_test_helpers import (
    ProjectsPaneTestApp,
    make_project_record,
)

_NOW = 1_720_000_000.0


def _repo(name: str) -> RepoRecord:
    return RepoRecord(
        name=name,
        kind="primary",
        project="alpha",
        project_key="alpha",
        path=f"/work/alpha/{name}",
        exists=True,
        auto_clone=False,
        description=None,
        source="ProjectSpec",
        env_name=None,
        sdd_storage=None,
    )


def _workspace(workspace_num: int) -> WorkspaceInventoryRecord:
    return WorkspaceInventoryRecord(
        workspace_num=workspace_num,
        project="alpha",
        project_key="alpha",
        project_state="enabled",
        checkout_dir=f"/work/alpha/alpha_{workspace_num}",
        exists=True,
        materialization="git-clone",
        role="claim",
        pinned=False,
        created_at=_NOW - 86400,
        last_used_at=_NOW - 120,
        generation=0,
        stale=False,
        cleanup_ttl_days=14,
        registry_path="/work/alpha/registry.json",
        claim_agent=None,
        claim_pid=None,
        claim_pid_alive=None,
        claim_cl_name=None,
        claim_timestamp=None,
    )


def _patch_data(
    monkeypatch: pytest.MonkeyPatch,
    records: list[ProjectRecordWire],
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: records,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.collect_project_inventory_counts",
        lambda *_args: ProjectCountsLoadResult({}),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.collect_repo_inventory",
        lambda *_args, **_kwargs: RepoInventory(
            (_repo("alpha"), _repo("alpha--plans"), _repo("alpha--research")),
            (),
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.collect_workspace_inventory",
        lambda *_args, **_kwargs: WorkspaceInventory(
            (_workspace(0), _workspace(1), _workspace(2)),
            (),
            (),
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.time.time",
        lambda: _NOW,
    )


def _default_records() -> list[ProjectRecordWire]:
    return [
        make_project_record("alpha"),
        make_project_record("beta"),
        make_project_record("gamma"),
    ]


def _plain(option_list: OptionList, index: int) -> str:
    option = option_list.get_option_at_index(index)
    prompt = option.prompt
    return prompt.plain if hasattr(prompt, "plain") else str(prompt)


def _hints(pane: ProjectsPane) -> str:
    return pane._hints_text()


async def test_projects_subtab_apostrophe_paints_hints_over_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_data(monkeypatch, _default_records())
    app = ProjectsPaneTestApp(projects_root=tmp_path)

    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        option_list = pane.query_one("#projects-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.pause()

        assert pane.jump_mode_active is True
        assert _plain(option_list, 0).startswith("[0] ")
        assert _plain(option_list, 2).startswith("[2] ")
        assert "JUMP ' first" in _hints(pane)


async def test_projects_subtab_hint_selects_project_and_updates_detail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_data(monkeypatch, _default_records())
    app = ProjectsPaneTestApp(projects_root=tmp_path)

    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        option_list = pane.query_one("#projects-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.press("2")
        await pilot.pause()

        assert pane.jump_mode_active is False
        assert pane.jump_back_stack == [0]
        assert option_list.highlighted == 2
        assert pane._selected_project_name() == "gamma"
        assert "gamma" in pane._detail_text(pane._selected_record()).plain
        assert not _plain(option_list, 2).startswith("[2] ")


async def test_projects_subtab_second_apostrophe_returns_to_previous_row(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_data(monkeypatch, _default_records())
    app = ProjectsPaneTestApp(projects_root=tmp_path)

    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        option_list = pane.query_one("#projects-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("apostrophe")
        await pilot.press("apostrophe")
        await pilot.pause()

        assert pane.jump_mode_active is False
        assert pane.jump_back_stack == []
        assert option_list.highlighted == 0


async def test_projects_subtab_escape_cancels_jump_without_moving(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_data(monkeypatch, _default_records())
    app = ProjectsPaneTestApp(projects_root=tmp_path)

    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        option_list = pane.query_one("#projects-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.press("escape")
        await pilot.pause()

        assert pane.jump_mode_active is False
        assert option_list.highlighted == 0
        assert not _plain(option_list, 0).startswith("[0] ")
        assert "' jump" in _hints(pane)


async def test_projects_filter_input_keeps_apostrophe_as_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_data(monkeypatch, _default_records())
    app = ProjectsPaneTestApp(projects_root=tmp_path)

    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()

        await pilot.press("slash")
        await pilot.press("apostrophe")
        await pilot.pause()

        assert pane.jump_mode_active is False
        assert pane._text_filter == "'"


async def test_projects_reload_after_delete_clears_jump_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    records = _default_records()
    _patch_data(monkeypatch, records)
    app = ProjectsPaneTestApp(projects_root=tmp_path)

    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()

        await pilot.press("apostrophe")
        await pilot.press("2")
        await pilot.pause()
        assert pane.jump_back_stack == [0]

        await pilot.press("apostrophe")
        await pilot.pause()
        assert pane.jump_mode_active is True

        records.pop()
        pane.action_reload_projects()
        await pilot.pause()

        assert pane.jump_mode_active is False
        assert pane.jump_back_stack == []


async def _goto_subtab(pilot, pane: ProjectsPane, subtab: str) -> None:
    repo_pane = pane.query_one(RepoInventoryPane)
    workspace_pane = pane.query_one(WorkspaceInventoryPane)
    for _ in range(20):
        if not repo_pane._loading and not workspace_pane._loading:
            break
        await pilot.pause()
    else:  # pragma: no cover - defensive
        raise AssertionError("inventory workers did not finish")
    while pane._active_subtab != subtab:
        await pilot.press("right_square_bracket")
        await pilot.pause()


@pytest.mark.parametrize(
    ("subtab", "pane_type", "list_id"),
    [
        ("repos", RepoInventoryPane, "repos-list"),
        ("workspaces", WorkspaceInventoryPane, "workspaces-list"),
    ],
)
async def test_inventory_subtab_jumps_within_its_own_rows(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    subtab: str,
    pane_type: type,
    list_id: str,
) -> None:
    _patch_data(monkeypatch, _default_records())
    app = ProjectsPaneTestApp(projects_root=tmp_path)

    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        await _goto_subtab(pilot, pane, subtab)
        inventory = pane.query_one(pane_type)
        option_list = inventory.query_one(f"#{list_id}", OptionList)
        projects_list = pane.query_one("#projects-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.pause()
        assert inventory.jump_mode_active is True
        assert pane.jump_mode_active is False
        assert _plain(option_list, 1).startswith("[1] ")
        # The parent projects list never gains hints from a sub-tab jump.
        assert not _plain(projects_list, 0).startswith("[0] ")
        assert "JUMP ' first" in inventory._hints_text()

        await pilot.press("2")
        await pilot.pause()

        assert inventory.jump_mode_active is False
        assert inventory.jump_back_stack == [0]
        assert option_list.highlighted == 2
        assert inventory._selected_record() is inventory._filtered_records[2]


async def test_switching_subtabs_clears_painted_hints(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_data(monkeypatch, _default_records())
    app = ProjectsPaneTestApp(projects_root=tmp_path)

    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        await _goto_subtab(pilot, pane, "repos")
        repo_pane = pane.query_one(RepoInventoryPane)
        repo_list = repo_pane.query_one("#repos-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.pause()
        assert repo_pane.jump_mode_active is True

        # The first sub-tab key is an invalid hint, so it only leaves jump mode.
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert pane._active_subtab == "repos"
        assert repo_pane.jump_mode_active is False
        assert not _plain(repo_list, 0).startswith("[0] ")

        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert pane._active_subtab == "workspaces"


async def test_subtab_switch_from_projects_clears_painted_hints(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_data(monkeypatch, _default_records())
    app = ProjectsPaneTestApp(projects_root=tmp_path)

    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        projects_list = pane.query_one("#projects-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.pause()
        assert pane.jump_mode_active is True

        # A programmatic switch (a sub-tab strip click, or the `r`/`w`
        # cross-navigation keys) must not strand hints on the projects list.
        pane._switch_to_subtab("repos")
        await pilot.pause()

        assert pane._active_subtab == "repos"
        assert pane.jump_mode_active is False
        assert not _plain(projects_list, 0).startswith("[0] ")


async def test_inventory_filter_input_keeps_apostrophe_as_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_data(monkeypatch, _default_records())
    app = ProjectsPaneTestApp(projects_root=tmp_path)

    async with app.run_test() as pilot:
        pane = app.query_one("#projects", ProjectsPane)
        await pilot.pause()
        await _goto_subtab(pilot, pane, "repos")
        repo_pane = pane.query_one(RepoInventoryPane)

        await pilot.press("slash")
        await pilot.press("apostrophe")
        await pilot.pause()

        assert repo_pane.jump_mode_active is False
        assert repo_pane._text_filter == "'"
