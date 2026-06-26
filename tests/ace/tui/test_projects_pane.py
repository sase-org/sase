"""Smoke test for the Projects tab of the SASE Admin Center (Phase 1).

Confirms the additive integration: the Projects pane is composed right of
Config, is reachable with ``]``, focuses its list when activated, and renders
the project rows. The behavioral parity tests still drive the standalone modal
during the coexistence window and are migrated to this pane in Phase 2.
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

        # ``]`` from Config lands directly on the new Projects tab.
        await page.press("]")
        await page.wait_for(lambda _s: modal._active_tab == "projects")
        assert switcher.current == "projects"

        pane = modal.query_one("#projects", ProjectsPane)
        option_list = pane.query_one("#projects-list", OptionList)
        # The default "active" state filter shows both seeded projects.
        assert option_list.option_count == 2
        # Activating the tab focuses the list (browse-first).
        assert page.app.focused is option_list
