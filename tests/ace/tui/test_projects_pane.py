"""Integration tests for the Projects tab of the SASE Admin Center.

Confirms the Projects pane is composed in alphabetical tab order, focuses its list when
activated, and renders the project rows. Also covers the filter input's key
forwarding (``[`` / ``]`` cycle the state filter while ``tab`` /
``shift+tab`` switch main tabs even when the filter is focused). The behavioral parity suite lives in
``tests/ace/tui/modals/test_project_management_modal_*.py``.
"""

from __future__ import annotations

import pytest
from textual.widgets import ContentSwitcher, OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.projects_pane import ProjectsPane

from tests.ace.tui.modals.project_management_modal_test_helpers import (
    make_project_record,
)
from tests.ace.tui._plugins_browser_pane_helpers import _core_versions


def _patch_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub every Admin Center pane loader so opening the modal is cheap."""
    config_result = cp._LoadResult(view=None, error=None, token=("tok", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kw: config_result)
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.get_all_prompts",
        lambda project=None: {},
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
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

        # ``Tab`` from Config lands on Logs, then Projects without switching
        # the hidden ACE main tab.
        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "logs")
        assert switcher.current == "logs"
        assert page.app.current_tab == "changespecs"

        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "projects")
        assert switcher.current == "projects"

        pane = modal.query_one("#projects", ProjectsPane)
        option_list = pane.query_one("#projects-list", OptionList)
        # The default "enabled" state filter shows both seeded projects.
        assert option_list.option_count == 2
        # Activating the tab focuses the list (browse-first).
        assert page.app.focused is option_list

        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "tasks")
        assert switcher.current == "tasks"
        assert page.app.current_tab == "changespecs"


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
        # leaves Projects for Logs (directly to its left).
        await page.press("shift+tab")
        await page.wait_for(lambda _s: modal._active_tab == "logs")
        assert switcher.current == "logs"
        assert page.app.current_tab == "changespecs"


async def _focus_projects_filter(page: AcePage) -> None:
    """Open the Projects tab filter input via the pane's ``/`` binding."""
    await page.press("/")
    await page.wait_for(
        lambda _s: (
            page.app.focused is not None and page.app.focused.id == "projects-filter"
        )
    )


async def test_projects_filter_forwards_brackets_to_cycle_state(
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
        assert pane._state_filter == "enabled"

        # Printable brackets are intercepted before Input can insert them and
        # cycle the Projects state filter locally in both directions, including
        # reverse wrapping from Active to All.
        await page.press("]")
        await page.wait_for(lambda _s: pane._state_filter == "sibling")
        assert modal._active_tab == "projects"

        await page.press("[")
        await page.wait_for(lambda _s: pane._state_filter == "enabled")

        await page.press("[")
        await page.wait_for(lambda _s: pane._state_filter == "all")
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
        assert pane._state_filter == "enabled"
        await _focus_projects_filter(page)

        # The Admin Center's priority Tab binding wins over focused-input
        # traversal and leaves the Projects state filter untouched.
        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "tasks")
        assert pane._state_filter == "enabled"
        assert page.app.current_tab == "changespecs"

        await page.press("shift+tab")
        await page.wait_for(lambda _s: modal._active_tab == "projects")
        assert pane._state_filter == "enabled"
        assert page.app.current_tab == "changespecs"
