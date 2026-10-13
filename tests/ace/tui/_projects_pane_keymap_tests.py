"""Projects-pane keymap, inventory, and help integration tests."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.project_inventory_panes import RepoInventoryPane
from sase.ace.tui.modals.project_management_rendering import hints_text
from sase.ace.tui.modals.projects_help_modal import ProjectsHelpModal
from sase.ace.tui.modals.projects_pane import ProjectsPane
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from tests.ace.tui._projects_pane_test_helpers import (
    focus_projects_filter,
    patch_panes,
)
from tests.ace.tui.modals.project_management_modal_test_helpers import (
    make_project_record,
)


async def test_inventory_escape_clears_project_before_closing_admin_center(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_panes(monkeypatch)
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        repo_pane = pane.query_one(RepoInventoryPane)
        repo_pane.set_project_filter("alpha")
        pane._switch_to_subtab("repos")

        await page.press("escape")

        assert page.app.screen is modal
        assert repo_pane.project_filter is None


async def test_configured_projects_bindings_dispatch_and_render_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rebound Projects-list keys drive both dispatch and the hints line."""
    patch_panes(monkeypatch)
    registry = load_keymap_registry(
        {
            "keymaps": {
                "projects": {
                    "toggle_project_mark": "f12",
                    "jump_to_entry": "f11",
                    "reload": "f10",
                    "set_current_project": "f9",
                }
            }
        }
    )

    async with AcePage() as page:
        page.app._keymap_registry = registry
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)

        hints = pane._hints_text()
        assert len(hints) <= pane.query_one("#projects-hints").size.width
        assert hints.startswith("n new")
        assert hints.endswith("? help")
        wide_hints = hints_text(set(), registry.projects, width=200)
        assert "f11 jump" in wide_hints
        assert "f12 mark" in wide_hints
        assert "f10 reload" in wide_hints
        assert "f9 current" in wide_hints
        # The old hardcoded keys no longer appear as live hints.
        assert "' jump" not in hints
        assert "m mark" not in hints

        await page.press("f12")
        assert "marked:1" in pane._summary_text().plain

        await page.press("f11")
        assert "JUMP f11 first" in pane._hints_text()
        await page.press("escape")

        await page.press("f10")
        await page.wait_for(lambda _s: pane._status_message == "Reloaded")


async def test_configured_cycle_subtab_keys_bubble_and_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rebound sub-tab cycle keys work from the list and from the filter input."""
    patch_panes(monkeypatch)
    registry = load_keymap_registry(
        {
            "keymaps": {
                "projects": {
                    "cycle_subtab": "f6",
                    "cycle_subtab_reverse": "f5",
                }
            }
        }
    )

    async with AcePage() as page:
        page.app._keymap_registry = registry
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)

        # The old default bracket keys no longer cycle sub-tabs.
        await page.press("]")
        await page.pause()
        assert pane._active_subtab == "projects"

        await page.press("f6")
        await page.wait_for(lambda _s: pane._active_subtab == "repos")

        await page.press("f5")
        await page.wait_for(lambda _s: pane._active_subtab == "projects")

        await focus_projects_filter(page)
        await page.press("f6")
        await page.wait_for(lambda _s: pane._active_subtab == "repos")
        assert pane.query_one("#projects-filter").value == ""


async def test_configured_inventory_bindings_dispatch_and_render_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rebound Repos/Workspaces sub-tab keys drive dispatch and hints."""
    patch_panes(monkeypatch)
    registry = load_keymap_registry(
        {
            "keymaps": {
                "projects": {
                    "pick_project": "f8",
                    "reload": "f7",
                    "clear_project_filter": "f4",
                }
            }
        }
    )

    async with AcePage() as page:
        page.app._keymap_registry = registry
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)
        repo_pane = pane.query_one(RepoInventoryPane)
        repo_pane.set_project_filter("alpha")
        pane._switch_to_subtab("repos")
        repo_pane.focus_default()

        hints = repo_pane._hints_text()
        assert "f8 pick project" in hints
        assert "f7 reload" in hints
        assert "f4 clear project" in hints

        await page.press("f4")
        await page.wait_for(lambda _s: repo_pane.project_filter is None)


async def test_projects_filter_applies_once_per_keystroke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_panes(monkeypatch)
    apply_calls: list[int] = []
    refresh_calls: list[int] = []
    original_apply = ProjectsPane._apply_filters
    original_refresh = ProjectsPane._refresh_options

    def _apply(self: ProjectsPane) -> None:
        apply_calls.append(1)
        original_apply(self)

    def _refresh(self: ProjectsPane, *, preferred_project: str | None = None) -> None:
        refresh_calls.append(1)
        original_refresh(self, preferred_project=preferred_project)

    monkeypatch.setattr(ProjectsPane, "_apply_filters", _apply)
    monkeypatch.setattr(ProjectsPane, "_refresh_options", _refresh)

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects-filter")))
        await focus_projects_filter(page)
        apply_calls.clear()
        refresh_calls.clear()

        await page.press("a")
        await page.pause()

        assert apply_calls == [1]
        assert refresh_calls == [1]


async def test_projects_help_opens_from_list_and_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_panes(monkeypatch)
    registry = load_keymap_registry({"keymaps": {"projects": {"help": "f5"}}})

    async with AcePage() as page:
        page.app._keymap_registry = registry
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects")))
        pane = modal.query_one("#projects", ProjectsPane)

        await page.press("f5")
        await page.expect_modal("ProjectsHelpModal")
        assert isinstance(page.app.screen, ProjectsHelpModal)
        footer = page.app.screen.query_one("#projects-help-footer")
        assert "f5/q/Esc close" in footer.render().plain

        await page.press("f5")
        await page.expect_modal("ConfigCenterModal")
        assert pane.is_mounted

        pane._switch_to_subtab("repos")
        await page.press("f5")
        await page.expect_modal("ProjectsHelpModal")
        await page.press("escape")
        await page.expect_modal("ConfigCenterModal")


async def test_show_new_project_key_clears_filter(
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
        assert pane.check_action("show_new_project", ()) is not False
        assert "s show new" in pane._hints_text()

        await page.press("s")
        await page.pause()

        assert pane._text_filter == ""
        assert filter_input.value == ""
        assert pane._selected_project_name() == "new-project"
        assert pane.check_action("show_new_project", ()) is False
