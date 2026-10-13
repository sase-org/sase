"""Integration tests for the Projects tab of the SASE Admin Center.

Confirms the Projects pane is composed in alphabetical tab order, focuses its list when
activated, and renders the project rows. Also covers the filter input's key
forwarding (``[`` / ``]`` cycle the project/repo/workspace sub-tabs while ``tab`` /
``shift+tab`` switch main tabs even when the filter is focused). The behavioral parity suite lives in
``tests/ace/tui/modals/test_project_management_modal_*.py``.
"""

from __future__ import annotations

from datetime import datetime
import weakref

import pytest
from textual.widgets import Button, ContentSwitcher, OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.commands import build_command_catalog, execute_command
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.new_project_modal import NewProjectModal, NewProjectSelection
from sase.ace.tui.modals.project_management_rendering import hints_text
from sase.ace.tui.modals.project_inventory_panes import RepoInventoryPane
from sase.ace.tui.modals.projects_help_modal import ProjectsHelpModal
from sase.ace.tui.modals.projects_pane import ProjectsPane
from sase.current_project import CurrentProject
from sase.ace.tui.modals.projects_pane import ProjectCountsLoadResult
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
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
    monkeypatch.setattr(
        "sase.macro.loader.get_all_project_local_prompts",
        lambda: {},
    )
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


async def test_admin_center_reaches_projects_tab_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#config-center-switcher")))

        switcher = modal.query_one("#config-center-switcher", ContentSwitcher)
        assert switcher.current == "config"

        # ``Tab`` from Config lands on Logs, Machines, Procs, then Projects
        # without switching the hidden ACE main tab.
        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "logs")
        assert switcher.current == "logs"
        assert page.app.current_tab == "artifacts"

        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "machines")
        assert switcher.current == "machines"
        assert page.app.current_tab == "artifacts"

        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "procs")
        assert switcher.current == "procs"
        assert page.app.current_tab == "artifacts"

        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "projects")
        assert switcher.current == "projects"

        pane = modal.query_one("#projects", ProjectsPane)
        option_list = pane.query_one("#projects-list", OptionList)
        # The default Projects sub-tab shows both seeded projects.
        assert option_list.option_count == 2
        # Activating the tab focuses the list (browse-first).
        assert page.app.focused is option_list

        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "statistics")
        assert switcher.current == "statistics"
        assert page.app.current_tab == "artifacts"


async def test_projects_session_restores_project_by_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    state = AdminCenterSessionState()
    state.projects.projects.record("beta", 0)

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects", session_state=state)
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: modal._active_tab == "projects")

        pane = modal.query_one("#projects", ProjectsPane)
        option_list = pane.query_one("#projects-list", OptionList)

        assert option_list.highlighted == 1
        assert state.projects.projects.identity == "beta"


async def test_projects_session_round_trips_current_project_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        lambda **_kwargs: CurrentProject(
            project_key="beta",
            display_name="beta",
            origin="project",
            origin_ref="beta",
            workflow_type="gh",
        ),
    )
    state = AdminCenterSessionState()

    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects", session_state=state)
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: modal._active_tab == "projects")
        pane = modal.query_one("#projects", ProjectsPane)
        await page.wait_for(lambda _s: pane._current_project_key == "beta")

        assert state.projects.current_project_key == "beta"
        assert state.projects.current_project_name == "beta"
        assert "current:+beta" in pane._summary_text().plain

        page.app.pop_screen()
        await page.pause()

        modal2 = ConfigCenterModal(initial_tab="projects", session_state=state)
        page.app.push_screen(modal2)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal2.query("#projects")))
        pane2 = modal2.query_one("#projects", ProjectsPane)
        assert pane2._current_project_loaded is True
        assert "current:+beta" in pane2._summary_text().plain


@pytest.mark.parametrize("pending_digit", [None, "1"])
async def test_admin_center_digit_owns_hidden_member_jump_state(
    monkeypatch: pytest.MonkeyPatch,
    pending_digit: str | None,
) -> None:
    _patch_panes(monkeypatch)
    members = [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="jump-test",
            project_file="/repos/demo/project.sase",
            status="RUNNING",
            start_time=datetime(2026, 7, 19, 12, 0, 0),
            raw_suffix=f"ts-member-{index}",
            agent_name=f"member-{index}",
            agent_clan="research",
        )
        for index in range(2)
    ]
    projected = project_clan_tree(members)
    container = projected[0]
    assert container.is_clan_container

    async with AcePage(initial_tab="agents") as page:
        page.app._agents = projected
        page.app.current_idx = 0
        page.app._current_group_key = None
        page.app._member_jump_pending_digit = pending_digit
        page.app._member_jump_pending_container_identity = (
            container.identity if pending_digit is not None else None
        )
        footer_refreshes: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_refresh_agent_footer_bindings_only",
            lambda: footer_refreshes.append(True),
        )

        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")

        await page.press("5")
        await page.wait_for(lambda _s: modal._active_tab == "projects")

        assert page.app._member_jump_pending_digit is None
        assert page.app._member_jump_pending_container_identity is None
        assert footer_refreshes == []


async def test_admin_center_leaves_projects_tab_with_shift_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#config-center-switcher")))

        switcher = modal.query_one("#config-center-switcher", ContentSwitcher)
        assert switcher.current == "projects"

        # With the list focused, the host modal's priority ``Shift+Tab`` binding
        # leaves Projects for Procs (directly to its left).
        await page.press("shift+tab")
        await page.wait_for(lambda _s: modal._active_tab == "procs")
        assert switcher.current == "procs"
        assert page.app.current_tab == "artifacts"


async def _focus_projects_filter(page: AcePage) -> None:
    """Open the Projects tab filter input via the pane's ``/`` binding."""
    await page.press("/")
    await page.wait_for(
        lambda _s: (
            page.app.focused is not None and page.app.focused.id == "projects-filter"
        )
    )


async def test_projects_filter_forwards_brackets_to_cycle_subtabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects-filter")))

        await _focus_projects_filter(page)

        pane = modal.query_one("#projects", ProjectsPane)
        strip = pane.query_one("#projects-subtabs", PanelTabStrip)
        assert pane._active_subtab == "projects"
        assert strip._build_content().plain == " PROJECTS  │  Repos  │  Workspaces "

        # Printable brackets are intercepted before Input can insert them and
        # cycle the Projects pane's real sub-tabs in both directions.
        await page.press("]")
        await page.wait_for(lambda _s: pane._active_subtab == "repos")
        assert modal._active_tab == "projects"
        assert strip._build_content().plain == " Projects  │  REPOS  │  Workspaces "

        await page.press("[")
        await page.wait_for(lambda _s: pane._active_subtab == "projects")
        assert strip._build_content().plain == " PROJECTS  │  Repos  │  Workspaces "

        await page.press("[")
        await page.wait_for(lambda _s: pane._active_subtab == "workspaces")
        assert strip._build_content().plain == " Projects  │  Repos  │  WORKSPACES "
        assert pane.query_one("#projects-filter").value == ""


async def test_projects_filter_yields_tab_to_admin_center(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects-filter")))

        pane = modal.query_one("#projects", ProjectsPane)
        assert pane._active_subtab == "projects"
        await _focus_projects_filter(page)

        # The Admin Center's priority Tab binding wins over focused-input
        # traversal and leaves the Projects sub-tab untouched.
        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "statistics")
        assert pane._active_subtab == "projects"
        assert page.app.current_tab == "artifacts"

        await page.press("shift+tab")
        await page.wait_for(lambda _s: modal._active_tab == "projects")
        assert pane._active_subtab == "projects"
        assert page.app.current_tab == "artifacts"


async def test_new_project_binding_is_scoped_and_filter_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
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
    _patch_panes(monkeypatch)
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
    _patch_panes(monkeypatch)
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
    _patch_panes(monkeypatch)
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
    _patch_panes(monkeypatch)
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


async def test_inventory_escape_clears_project_before_closing_admin_center(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
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
    _patch_panes(monkeypatch)
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
    _patch_panes(monkeypatch)
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

        await _focus_projects_filter(page)
        await page.press("f6")
        await page.wait_for(lambda _s: pane._active_subtab == "repos")
        assert pane.query_one("#projects-filter").value == ""


async def test_configured_inventory_bindings_dispatch_and_render_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rebound Repos/Workspaces sub-tab keys drive dispatch and hints."""
    _patch_panes(monkeypatch)
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
    _patch_panes(monkeypatch)
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
        await _focus_projects_filter(page)
        apply_calls.clear()
        refresh_calls.clear()

        await page.press("a")
        await page.pause()

        assert apply_calls == [1]
        assert refresh_calls == [1]


async def test_projects_help_opens_from_list_and_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
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
