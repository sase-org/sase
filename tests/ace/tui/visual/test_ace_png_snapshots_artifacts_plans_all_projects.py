"""All-projects PNG coverage for the ACE Artifacts → Plans pane."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from tests.ace.tui._artifacts_plans_helpers import (
    _all_choices,
    _all_projects_snapshot,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_artifacts_plans_all_projects_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    snapshot = _all_projects_snapshot(tmp_path)
    snapshot = replace(
        snapshot,
        proposals=(
            replace(
                snapshot.proposals[0],
                plan_path="/workspace/beta--plans/202607/ship_plan_browser.md",
            ),
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _all_choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("[")
        await page.expect_state("artifacts_subtab", "plans")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.press("j", "k")
        await page.wait_for(
            lambda _state: (
                (row := pane.selected_row()) is not None
                and row.row_id == "proposal:beta:proposal-1"
            )
        )
        await page.wait_for(
            lambda _state: (
                pane._detail_debouncer is None or not pane._detail_debouncer.is_pending
            )
        )
        pane._update_detail()
        await page.press("p")
        await page.expect_modal("InventoryProjectPicker")
        await page.press("escape")
        await page.wait_for(lambda _state: page.app.screen is page.app.screen_stack[0])
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()

        ace_png_visual.assert_page_png(
            page,
            "artifacts_plans_all_projects_populated_120x40",
            title="ACE Artifacts - Plans all projects",
        )
