"""Integration tests for the Projects tab of the SASE Admin Center.

Confirms the Projects pane is composed after Logs, focuses its list when
activated, and renders the project rows. Also covers the filter input's key
forwarding (``[`` / ``]`` switch tabs and ``tab`` / ``shift+tab`` cycle the
state filter even while the filter is focused). The behavioral parity suite lives in
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
    plugins_result = pbp._PluginsLoadResult(catalog=None, error="stub", now=0.0)
    monkeypatch.setattr(pbp, "_load_plugins_catalog", lambda **_kw: plugins_result)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: [
            make_project_record("alpha", state="active"),
            make_project_record("beta", state="active"),
        ],
    )


async def test_admin_center_reaches_logs_then_projects_tab_from_config(
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

        # ``]`` from Config lands on Tasks, then Logs, then Projects.
        await page.press("]")
        await page.wait_for(lambda _s: modal._active_tab == "tasks")
        assert switcher.current == "tasks"

        await page.press("]")
        await page.wait_for(lambda _s: modal._active_tab == "logs")
        assert switcher.current == "logs"

        await page.press("]")
        await page.wait_for(lambda _s: modal._active_tab == "projects")
        assert switcher.current == "projects"

        pane = modal.query_one("#projects", ProjectsPane)
        option_list = pane.query_one("#projects-list", OptionList)
        # The default "active" state filter shows both seeded projects.
        assert option_list.option_count == 2
        # Activating the tab focuses the list (browse-first).
        assert page.app.focused is option_list


async def test_admin_center_leaves_projects_tab_with_left_bracket(
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

        # With the list focused, the host modal's own ``[`` binding leaves
        # Projects for Logs (directly to its left).
        await page.press("[")
        await page.wait_for(lambda _s: modal._active_tab == "logs")
        assert switcher.current == "logs"


async def _focus_projects_filter(page: AcePage) -> None:
    """Open the Projects tab filter input via the pane's ``/`` binding."""
    await page.press("/")
    await page.wait_for(
        lambda _s: (
            page.app.focused is not None and page.app.focused.id == "projects-filter"
        )
    )


async def test_projects_filter_forwards_bracket_to_switch_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects-filter")))

        await _focus_projects_filter(page)

        # ``]`` is swallowed by the focused Input as text unless forwarded;
        # the filter forwards it to the host's next-tab action (→ Plugins).
        await page.press("]")
        await page.wait_for(lambda _s: modal._active_tab == "plugins")
        switcher = modal.query_one("#config-center-switcher", ContentSwitcher)
        assert switcher.current == "plugins"


async def test_projects_filter_forwards_tab_to_cycle_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="projects")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#projects-filter")))

        pane = modal.query_one("#projects", ProjectsPane)
        assert pane._state_filter == "active"
        await _focus_projects_filter(page)

        # ``tab`` / ``shift+tab`` cycle the state filter even while the filter
        # is focused (preserving the old modal's priority-binding behavior).
        await page.press("tab")
        await page.wait_for(lambda _s: pane._state_filter == "sibling")
        assert pane._state_filter == "sibling"

        await page.press("shift+tab")
        await page.wait_for(lambda _s: pane._state_filter == "active")
        assert pane._state_filter == "active"
