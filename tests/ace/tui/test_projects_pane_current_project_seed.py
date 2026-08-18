"""Current-project seeding of the Projects tab's Repos/Workspaces filters."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.project_inventory_panes import (
    RepoInventoryPane,
    WorkspaceInventoryPane,
)
from sase.ace.tui.modals.projects_pane import ProjectsPane
from sase.current_project import CurrentProject

from tests.ace.tui.test_projects_pane import _patch_panes


def _current_project(project_key: str) -> CurrentProject:
    return CurrentProject(
        project_key=project_key,
        display_name=project_key,
        origin="project",
        origin_ref=project_key,
        workflow_type="gh",
    )


async def test_seeds_inventory_filters_from_current_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        lambda: _current_project("alpha"),
    )

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        repo_pane = pane.query_one(RepoInventoryPane)
        workspace_pane = pane.query_one(WorkspaceInventoryPane)

        await page.wait_for(lambda _s: repo_pane.project_filter == "alpha")
        assert workspace_pane.project_filter == "alpha"
        assert pane._session_state.project_filter_seeded is True


async def test_seeded_session_state_is_not_reapplied_on_remount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    resolve_calls: list[int] = []

    def fake_resolve() -> CurrentProject | None:
        resolve_calls.append(1)
        return _current_project("alpha")

    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project", fake_resolve
    )
    state = AdminCenterSessionState()

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects", session_state=state)
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        repo_pane = pane.query_one(RepoInventoryPane)
        await page.wait_for(lambda _s: repo_pane.project_filter == "alpha")

        # The user escapes the seeded filter, then closes Admin Center.
        pane._switch_to_subtab("repos")
        await page.press("escape")
        assert repo_pane.project_filter is None
        assert state.projects.repos_project_filter is None
        assert len(resolve_calls) == 1

        page.app.pop_screen()
        await page.pause()

        # Reopening Admin Center mounts a fresh ProjectsPane bound to the
        # same session state; the escaped filter must not be reseeded.
        modal2 = ConfigCenterModal(initial_tab="projects", session_state=state)
        page.app.push_screen(modal2)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal2.query("#projects")))
        pane2 = modal2.query_one("#projects", ProjectsPane)
        repo_pane2 = pane2.query_one(RepoInventoryPane)
        await page.pause()
        assert repo_pane2.project_filter is None
        assert len(resolve_calls) == 1
