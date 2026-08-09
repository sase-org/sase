"""ACE PNG snapshot for the shared inventory project picker."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.inventory_project_picker import InventoryProjectPicker
from sase.ace.tui.modals.project_inventory_panes import RepoInventoryPane
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


async def test_inventory_project_picker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        _, pane = await _open_projects_modal(page)
        repo_pane = pane.query_one(RepoInventoryPane)
        await page.wait_for(lambda _s: not repo_pane._loading)
        pane._switch_to_subtab("repos")
        repo_pane.action_pick_project()
        await page.expect_modal("InventoryProjectPicker")
        assert isinstance(page.app.screen, InventoryProjectPicker)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "inventory_project_picker_120x40",
            title="ACE SASE Admin Center — inventory project picker",
        )
