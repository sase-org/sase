"""Projects-pane navigation and session integration tests."""

from __future__ import annotations

from datetime import datetime

import pytest
from textual.widgets import ContentSwitcher, OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.projects_pane import ProjectsPane
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from sase.current_project import CurrentProject
from tests.ace.tui._projects_pane_test_helpers import (
    focus_projects_filter,
    patch_panes,
)


async def test_admin_center_reaches_projects_tab_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_panes(monkeypatch)
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
    patch_panes(monkeypatch)
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
    patch_panes(monkeypatch)
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
    patch_panes(monkeypatch)
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
    patch_panes(monkeypatch)
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


async def test_projects_filter_forwards_brackets_to_cycle_subtabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_panes(monkeypatch)
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects-filter")))

        await focus_projects_filter(page)

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
    patch_panes(monkeypatch)
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects-filter")))

        pane = modal.query_one("#projects", ProjectsPane)
        assert pane._active_subtab == "projects"
        await focus_projects_filter(page)

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
