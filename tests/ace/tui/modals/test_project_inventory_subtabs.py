"""Interactions for repository/workspace sub-tabs and their shared picker."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.pilot import Pilot
from textual.widgets import OptionList

from sase.ace.tui.modals.inventory_project_picker import InventoryProjectPicker
from sase.ace.tui.modals.project_inventory_panes import (
    RepoInventoryPane,
    WorkspaceInventoryPane,
)
from sase.ace.tui.modals.project_inventory_rendering import (
    repo_record_label,
    repo_summary_text,
)
from sase.ace.tui.modals.project_management_rendering import ProjectInventoryCounts
from sase.ace.tui.modals.projects_pane import (
    ProjectsPane,
    _ProjectCountsLoadResult,
)
from sase.repo_inventory import RepoInventory, RepoInventoryIssue, RepoRecord
from sase.workspace_provider.inventory import (
    WorkspaceInventory,
    WorkspaceInventoryIssue,
    WorkspaceInventoryRecord,
)

from .project_management_modal_test_helpers import (
    ProjectsPaneTestApp,
    make_project_record,
)

_NOW = 1_720_000_000.0


def _repo(
    name: str,
    *,
    project: str = "alpha",
    project_key: str | None = None,
    kind: str = "primary",
    exists: bool = True,
) -> RepoRecord:
    return RepoRecord(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        project=project,
        project_key=project_key or project,
        path=f"/work/{project}/{name}",
        exists=exists,
        auto_clone=kind != "primary",
        description=f"{name} description",
        source="ProjectSpec" if kind == "primary" else "linked_repos config",
        env_name=None if kind == "primary" else name.upper().replace("-", "_"),
        sdd_storage="sidecar_repos" if kind == "sidecar" else None,
    )


def _workspace(
    workspace_num: int,
    *,
    project: str = "alpha",
    project_key: str | None = None,
    project_state: str = "enabled",
    exists: bool = True,
    stale: bool = False,
    claim_agent: str | None = None,
    claim_pid_alive: bool | None = None,
) -> WorkspaceInventoryRecord:
    return WorkspaceInventoryRecord(
        workspace_num=workspace_num,
        project=project,
        project_key=project_key or project,
        project_state=project_state,
        checkout_dir=f"/work/{project}/{project}_{workspace_num}",
        exists=exists,
        materialization="git-clone",
        role="primary" if workspace_num == 0 else "claim",
        pinned=workspace_num == 0,
        created_at=_NOW - 40 * 86400,
        last_used_at=_NOW - (31 * 86400 if stale else 120),
        generation=0,
        stale=stale,
        cleanup_ttl_days=14,
        registry_path=f"/work/{project}/registry.json",
        claim_agent=claim_agent,
        claim_pid=4242 if claim_agent else None,
        claim_pid_alive=claim_pid_alive,
        claim_cl_name="inventory-phase" if claim_agent else None,
        claim_timestamp="260713_094059" if claim_agent else None,
    )


def test_external_repo_inventory_uses_amber_kind_style() -> None:
    external = _repo("gh:pallets/click", kind="external")

    label = repo_record_label(external)
    summary = repo_summary_text(
        [external],
        project=None,
        text_filter="",
        issue_count=0,
        loading=False,
        error="",
    )

    assert "external" in label.plain
    assert any(str(span.style) == "bold #FFAF00" for span in label.spans)
    assert "external:1" in summary.plain
    assert any(str(span.style) == "bold #FFAF00" for span in summary.spans)


def _patch_inventory_data(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[RepoRecord], list[WorkspaceInventoryRecord]]:
    project_records = [
        make_project_record("alpha", state="enabled"),
        make_project_record("beta", state="disabled", launchable=False),
    ]
    repos = [
        _repo("alpha"),
        _repo("alpha--plans", kind="sidecar"),
        _repo("alpha-core", kind="linked", exists=False),
        _repo("beta", project="beta"),
        _repo("chezmoi", project="home", kind="linked"),
    ]
    workspaces = [
        _workspace(0),
        _workspace(11, claim_agent="ace(run)-260713", claim_pid_alive=True),
        _workspace(
            12,
            exists=False,
            claim_agent="abandoned-agent",
            claim_pid_alive=False,
        ),
        _workspace(
            42,
            project="beta",
            project_state="disabled",
            stale=True,
        ),
    ]
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: project_records,
    )
    counts = {
        "alpha": ProjectInventoryCounts(repo_count=3, workspace_count=3),
        "beta": ProjectInventoryCounts(repo_count=1, workspace_count=1),
    }
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane._collect_project_inventory_counts",
        lambda *_args: _ProjectCountsLoadResult(counts),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.collect_repo_inventory",
        lambda *_args, **_kwargs: RepoInventory(
            tuple(repos),
            (RepoInventoryIssue("alpha", "linked repo warning"),),
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.collect_workspace_inventory",
        lambda *_args, **_kwargs: WorkspaceInventory(
            tuple(workspaces),
            (),
            (WorkspaceInventoryIssue("alpha", "registry warning"),),
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.time.time",
        lambda: _NOW,
    )
    return repos, workspaces


async def _wait_for_inventory(pilot: Pilot[None], pane: ProjectsPane) -> None:
    repo_pane = pane.query_one(RepoInventoryPane)
    workspace_pane = pane.query_one(WorkspaceInventoryPane)
    for _ in range(20):
        if not repo_pane._loading and not workspace_pane._loading:
            return
        await pilot.pause()
    raise AssertionError("inventory workers did not finish")


async def test_repo_and_workspace_subtabs_render_cached_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_inventory_data(monkeypatch)
    app = ProjectsPaneTestApp(projects_root=tmp_path)

    async with app.run_test() as pilot:
        pane = app.query_one(ProjectsPane)
        await _wait_for_inventory(pilot, pane)

        await pilot.press("]")
        repo_pane = pane.query_one(RepoInventoryPane)
        assert pane._active_subtab == "repos"
        # Disabled beta is absent by default; home linked repos remain visible.
        assert [record.name for record in repo_pane._scoped_records] == [
            "alpha",
            "alpha--plans",
            "alpha-core",
            "chezmoi",
        ]
        assert "primary:1" in repo_pane._summary_text().plain
        assert "sidecar:1" in repo_pane._summary_text().plain
        assert "linked:2" in repo_pane._summary_text().plain

        repo_list = repo_pane.query_one("#repos-list", OptionList)
        repo_list.highlighted = 2
        repo_pane._update_detail()
        detail = repo_pane._detail_text(repo_pane._selected_record()).plain
        assert "Status: missing" in detail
        assert "SASE_LINKED_REPO_ALPHA_CORE_DIR" in detail
        assert "linked repo warning" in detail

        await pilot.press("]")
        workspace_pane = pane.query_one(WorkspaceInventoryPane)
        assert pane._active_subtab == "workspaces"
        assert [record.workspace_num for record in workspace_pane._scoped_records] == [
            0,
            11,
            12,
        ]
        workspace_list = workspace_pane.query_one("#workspaces-list", OptionList)
        workspace_list.highlighted = 2
        workspace_pane._update_detail()
        row = workspace_pane._record_label(workspace_pane._filtered_records[2]).plain
        assert "abandoned-agent ⚠ dead" in row
        assert "missing" in row
        detail = workspace_pane._detail_text(workspace_pane._selected_record()).plain
        assert "pid 4242 (dead)" in detail
        assert "sase workspace repair" in detail
        assert "registry warning" in detail


async def test_cross_navigation_and_escape_surface_disabled_workspaces(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_inventory_data(monkeypatch)
    app = ProjectsPaneTestApp(projects_root=tmp_path)

    async with app.run_test() as pilot:
        pane = app.query_one(ProjectsPane)
        await _wait_for_inventory(pilot, pane)
        pane.query_one("#projects-list", OptionList).highlighted = 1

        await pilot.press("w")
        workspace_pane = pane.query_one(WorkspaceInventoryPane)
        assert pane._active_subtab == "workspaces"
        assert workspace_pane.project_filter == "beta"
        assert [
            record.workspace_num for record in workspace_pane._filtered_records
        ] == [42]
        assert "project:beta" in workspace_pane._summary_text().plain

        await pilot.press("escape")
        assert workspace_pane.project_filter is None
        assert pane._active_subtab == "workspaces"
        # Clearing the explicit filter returns to enabled projects only.
        assert 42 not in {
            record.workspace_num for record in workspace_pane._filtered_records
        }

        await pilot.press("[")
        await pilot.press("[")
        assert pane._active_subtab == "projects"
        pane.query_one("#projects-list", OptionList).highlighted = 0
        await pilot.press("r")
        assert pane._active_subtab == "repos"
        assert pane.query_one(RepoInventoryPane).project_filter == "alpha"


async def test_shared_project_picker_filters_both_inventory_views(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_inventory_data(monkeypatch)
    app = ProjectsPaneTestApp(projects_root=tmp_path)

    async with app.run_test() as pilot:
        pane = app.query_one(ProjectsPane)
        await _wait_for_inventory(pilot, pane)
        await pilot.press("]")
        repo_pane = pane.query_one(RepoInventoryPane)

        await pilot.press("p")
        assert isinstance(app.screen, InventoryProjectPicker)
        await pilot.press("b", "e", "t", "a")
        picker = app.screen
        assert isinstance(picker, InventoryProjectPicker)
        assert [choice.project_key for choice in picker._filtered_choices] == ["beta"]
        # "All projects" stays first, so move once to the beta row.
        await pilot.press("down", "enter")
        await pilot.pause()

        assert app.screen is app.screen_stack[0]
        assert repo_pane.project_filter == "beta"
        assert [record.name for record in repo_pane._filtered_records] == ["beta"]
        assert "project:beta" in repo_pane._summary_text().plain


def test_reload_requests_are_coalesced_while_worker_is_active(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _patch_inventory_data(monkeypatch)
    pane = RepoInventoryPane(
        projects_root=tmp_path,
        project_records=[make_project_record("alpha")],
    )
    pane._loading = True

    pane._start_inventory_load()

    assert pane._reload_pending is True
