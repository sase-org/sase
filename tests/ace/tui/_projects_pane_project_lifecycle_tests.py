"""Projects-pane creation and lifecycle integration tests."""

from __future__ import annotations

import pytest
from textual.widgets import Button, OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.commands import build_command_catalog, execute_command
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.new_project_modal import NewProjectModal
from sase.ace.tui.modals.projects_pane import ProjectsPane
from sase.current_project import CurrentProject
from tests.ace.tui._projects_pane_test_helpers import patch_panes
from tests.ace.tui.modals.project_management_modal_test_helpers import (
    make_project_record,
)


async def test_new_project_binding_is_scoped_and_filter_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_panes(monkeypatch)
    opened: list[ProjectsPane] = []
    monkeypatch.setattr(
        ProjectsPane, "action_new_project", lambda pane: opened.append(pane)
    )

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)

        await page.press("n")
        assert opened == [pane]

        pane._switch_to_subtab("repos")
        await page.press("n")
        assert opened == [pane]

        pane._switch_to_subtab("projects")
        filter_input = pane.query_one("#projects-filter")
        filter_input.focus()
        await page.press("n")
        assert filter_input.value == "n"
        assert opened == [pane]


async def test_new_project_palette_opener_is_one_shot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_panes(monkeypatch)
    opened: list[ProjectsPane] = []
    monkeypatch.setattr(
        ProjectsPane, "action_new_project", lambda pane: opened.append(pane)
    )
    registry = load_keymap_registry({})
    catalog = {spec.id: spec for spec in build_command_catalog(registry)}

    async with AcePage() as page:
        execute_command(page.app, catalog["projects.new"])
        await page.wait_for(lambda _s: isinstance(page.app.screen, ConfigCenterModal))
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        await page.wait_for(lambda _s: len(opened) == 1)

        modal.switch_to_tab("config")
        await page.wait_for(lambda _s: modal._active_tab == "config")
        modal.switch_to_tab("projects")
        await page.wait_for(lambda _s: modal._active_tab == "projects")
        await page.pause()

        assert len(opened) == 1


async def test_new_project_gets_current_provider_and_owner_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_panes(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        lambda **_kwargs: CurrentProject(
            project_key="gh_sase-org__sase",
            display_name="sase",
            origin="project",
            origin_ref="gh_sase-org__sase",
            workflow_type="gh",
        ),
    )

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        await page.wait_for(
            lambda _s: (
                pane._current_project_loaded and pane._current_project is not None
            )
        )
        captured: list[object] = []
        monkeypatch.setattr(
            page.app,
            "push_screen",
            lambda screen, _callback=None: captured.append(screen),
        )

        pane.action_new_project()

        assert len(captured) == 1
        wizard = captured[0]
        assert isinstance(wizard, NewProjectModal)
        assert wizard._current_workflow_type == "gh"
        assert wizard._current_project_owner == "sase-org"


async def test_post_add_keeps_filter_and_offers_show_new_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_panes(monkeypatch)
    records = [
        make_project_record("alpha", state="enabled"),
        make_project_record("new-project", state="enabled"),
    ]
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: records,
    )
    warmed: list[bool] = []
    invalidated: list[ProjectsPane] = []
    lifecycle: list[ProjectsPane] = []
    monkeypatch.setattr(
        "sase.project_tags.ensure_project_tag_catalog",
        lambda: warmed.append(True),
    )
    monkeypatch.setattr(
        ProjectsPane,
        "_invalidate_current_project_indicator",
        lambda pane: invalidated.append(pane),
    )
    monkeypatch.setattr(
        ProjectsPane,
        "_notify_lifecycle_changed",
        lambda pane: lifecycle.append(pane),
    )

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        filter_input = pane.query_one("#projects-filter")
        filter_input.value = "alpha"
        await page.pause()

        pane._integrate_added_project("new-project")

        show_button = pane.query_one("#projects-show-new-project", Button)
        assert pane._text_filter == "alpha"
        assert filter_input.value == "alpha"
        assert show_button.display
        assert "hidden by the current filter" in pane._status_message
        assert invalidated == [pane]
        assert lifecycle == [pane]
        await page.wait_for(lambda _s: bool(warmed))

        await page.click("#projects-show-new-project")

        assert pane._text_filter == ""
        assert filter_input.value == ""
        assert not show_button.display
        assert pane._selected_project_name() == "new-project"


async def test_empty_projects_state_names_new_project_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_panes(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_args, **_kwargs: [],
    )

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        option = pane.query_one("#projects-list", OptionList).options[0]

        assert option.prompt.plain == "No projects yet — press n to add or create one"
