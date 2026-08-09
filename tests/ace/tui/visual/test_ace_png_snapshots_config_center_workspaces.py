"""ACE PNG snapshot for the Admin Center Workspaces sub-tab."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.project_inventory_panes import WorkspaceInventoryPane
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _build_view,
    _config_layers,
    _config_schema,
    _open_projects_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_project_records,
    _patch_xprompt_sources,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _patch_admin_center(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_project_records(monkeypatch)


async def test_config_center_workspaces_subtab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        _, pane = await _open_projects_modal(page)
        workspace_pane = pane.query_one(WorkspaceInventoryPane)
        await wait_for_state(
            page,
            lambda: not workspace_pane._loading,
            description="workspace inventory load",
        )
        pane._switch_to_subtab("workspaces")
        workspace_pane._update_detail()
        page.app.screen.refresh(layout=True)
        await wait_for_state(
            page,
            lambda: (
                pane._active_subtab == "workspaces"
                and workspace_pane.query_one("#workspaces-list").has_focus
            ),
            description="workspace inventory sub-tab focus",
        )
        await wait_for_svg_contains(page, "Workspace")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_workspaces_tab_120x40",
            title="ACE SASE Admin Center — workspace inventory",
        )
