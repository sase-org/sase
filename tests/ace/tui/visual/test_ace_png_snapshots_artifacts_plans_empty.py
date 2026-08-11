"""Empty-state PNG coverage for the ACE Artifacts → Plans pane."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from tests.ace.tui._artifacts_plans_helpers import _choices, _snapshot
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_artifacts_plans_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    snapshot = replace(
        _snapshot(tmp_path),
        proposals=(),
        active=(),
        archive=(),
        bead_plan_links={},
        linked_plan_documents={},
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.plans_pane.load_plans_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("files_subtab", "plans")
        pane = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await wait_for_svg_contains(page, "No pending proposals")
        await page.press("p")
        await page.expect_modal("InventoryProjectPicker")
        await page.press("escape")
        await page.wait_for(lambda _state: page.app.screen is page.app.screen_stack[0])
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_plans_empty_120x40",
            title="ACE Artifacts - Plans empty",
        )
