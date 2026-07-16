"""ACE PNG visual snapshot coverage for Artifacts → Plans."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.plans_pane import ArtifactsPlansPane
from tests.ace.tui.test_artifacts_plans import _choices, _snapshot
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_artifacts_plans_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    snapshot = _snapshot(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
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
        await page.press("j", "l", "j")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_plans_populated_120x40",
            title="ACE Artifacts - Plans populated",
        )
