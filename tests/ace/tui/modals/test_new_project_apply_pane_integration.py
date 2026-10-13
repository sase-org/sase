"""Projects pane integration coverage for New Project apply completion."""

from __future__ import annotations

import weakref

import pytest
from textual.widgets import Button

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.new_project_modal import NewProjectModal, NewProjectSelection
from sase.ace.tui.modals.projects_pane import ProjectCountsLoadResult, ProjectsPane
from sase.repo_inventory import RepoInventory
from sase.workspace_provider.inventory import WorkspaceInventory

from tests.ace.tui.modals.project_management_modal_test_helpers import (
    make_project_record,
)
from tests.ace.tui._plugins_browser_pane_helpers import _core_versions


def _patch_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub every Admin Center pane loader so opening the modal is cheap."""
    config_result = cp._LoadResult(view=None, error=None, token=("tok", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kw: config_result)
    monkeypatch.setattr(
        "sase.ace.tui.modals.macro_browser_pane.get_all_prompts",
        lambda project=None: {},
    )
    monkeypatch.setattr("sase.macro.loader.get_all_project_local_prompts", lambda: {})
    plugins_result = pbp._PluginsLoadResult(
        catalog=None, error="stub", now=0.0, core_versions=_core_versions()
    )
    monkeypatch.setattr(pbp, "_load_plugins_catalog", lambda **_kw: plugins_result)
    monkeypatch.setattr(pbp, "_collect_installed_core_versions", _core_versions)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: [
            make_project_record("alpha", state="enabled"),
            make_project_record("beta", state="enabled"),
        ],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.collect_project_inventory_counts",
        lambda *_args: ProjectCountsLoadResult({}),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.collect_repo_inventory",
        lambda *_args, **_kwargs: RepoInventory(()),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.collect_workspace_inventory",
        lambda *_args, **_kwargs: WorkspaceInventory((), ()),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.get_known_project_workspaces",
        lambda **_kwargs: {},
    )


async def test_new_project_selection_outcomes_and_idempotency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    loads: list[int] = []
    original_load = ProjectsPane._load_records

    def _load(self: ProjectsPane) -> bool:
        loads.append(1)
        return original_load(self)

    monkeypatch.setattr(ProjectsPane, "_load_records", _load)

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        loads.clear()

        pane._handle_new_project_selection(
            NewProjectSelection("show-project", project_key="alpha")
        )
        assert pane._status_message == "Showing alpha"
        assert pane._selected_project_name() == "alpha"
        assert loads == [1]

        pane.action_next_option()
        assert pane._selected_project_name() == "beta"

        pane._handle_new_project_selection(
            NewProjectSelection("show-project", project_key="alpha")
        )
        assert pane._status_message == "Showing alpha"
        assert pane._selected_project_name() == "alpha"
        assert loads == [1, 1]

        pane._handle_new_project_selection(
            NewProjectSelection("added", project_key="alpha", operation_id="add-1")
        )
        assert pane._status_message == "Project added"
        assert loads == [1, 1, 1]
        pane._handle_new_project_selection(
            NewProjectSelection("show", project_key="alpha", operation_id="add-1")
        )
        assert pane._status_message == "Project added"
        assert pane._selected_project_name() == "alpha"
        assert loads == [1, 1, 1]

        pane._handle_new_project_selection(
            NewProjectSelection("added", project_key="beta", operation_id="add-2")
        )
        assert pane._status_message == "Project added"
        assert pane._selected_project_name() == "beta"
        assert loads == [1, 1, 1, 1]


async def test_apply_complete_finds_pane_on_screen_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
    from sase.ace.tui.modals._new_project_apply_shared import (
        find_projects_pane,
        on_project_apply_complete,
    )
    from sase.ace.tui.proc_observer import ObservedProc
    from sase.core.time import local_now

    _patch_panes(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.modals._new_project_apply_shared._persist_add_preferences_async",
        lambda _intent: None,
    )
    records = [
        make_project_record("alpha", state="enabled"),
        make_project_record("new-project", state="enabled"),
    ]
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: records,
    )

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        wizard = NewProjectModal(provider_metadata=())
        page.app.push_screen(wizard)
        await page.pause()
        page.app.pop_screen()
        await page.pause()

        assert find_projects_pane(page.app) is pane
        completion = TrackedProcCompletion(
            proc_info=ObservedProc(
                proc_id="add-1",
                proc_type="project.add",
                cl_name="",
                project_file="",
                status="success",
                message="ok",
                started_at=local_now(),
            ),
            success=True,
            message="ok",
            output="",
        )
        on_project_apply_complete(
            page.app,
            weakref.ref(wizard),
            {"mode": "add", "project_key": "new-project"},
            completion,
        )
        assert pane._selected_project_name() == "new-project"
        assert pane._status_message == "Project added"
        on_project_apply_complete(
            page.app,
            weakref.ref(wizard),
            {"mode": "add", "project_key": "new-project"},
            completion,
        )
        pane._handle_new_project_selection(
            NewProjectSelection("show", project_key="new-project", operation_id="add-1")
        )
        assert pane._status_message == "Project added"
        assert pane._selected_project_name() == "new-project"


async def test_independent_filtered_outcome_after_completion_offers_show_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    records = [
        make_project_record("alpha", state="enabled"),
        make_project_record("new-project", state="enabled"),
    ]
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: records,
    )

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)

        pane._integrate_added_project("new-project", operation_id="add-1")
        assert pane._selected_project_name() == "new-project"
        assert pane._status_message == "Project added"

        filter_input = pane.query_one("#projects-filter")
        filter_input.value = "alpha"
        await page.pause()
        assert pane._text_filter == "alpha"

        pane._integrate_added_project(
            "new-project", outcome="added", operation_id="add-2"
        )
        show_button = pane.query_one("#projects-show-new-project", Button)
        assert show_button.display
        assert "hidden by the current filter" in pane._status_message
        assert pane.check_action("show_new_project", ()) is not False


async def test_ready_current_invalidates_stacked_projects_pane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.current_project import SetCurrentProjectOutcome

    _patch_panes(monkeypatch)
    invalidations: list[ProjectsPane] = []
    monkeypatch.setattr(
        ProjectsPane,
        "_invalidate_current_project_indicator",
        lambda pane: invalidations.append(pane),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals._new_project_apply_ready.set_current_project",
        lambda _key: SetCurrentProjectOutcome(
            status="set", project=None, message="Set current project"
        ),
    )

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        wizard = NewProjectModal(provider_metadata=())
        page.app.push_screen(wizard)
        await page.pause()
        await wizard._set_current_key("alpha")
        await page.pause()

        assert invalidations == [pane]
