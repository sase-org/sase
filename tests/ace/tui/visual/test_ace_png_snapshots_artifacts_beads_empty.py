"""Empty-state PNG coverage for the ACE Artifacts → Beads pane."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from textual.widgets import Markdown

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from tests.ace.tui._artifacts_beads_helpers import snapshot as _snapshot
from tests.ace.tui._artifacts_plans_helpers import _choices
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_artifacts_beads_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    snapshot = replace(
        _snapshot(tmp_path),
        tasks=(),
        epics=(),
        phases_by_epic={},
        ready_ids=frozenset(),
        blocked_ids=frozenset(),
        plan_links={},
        triage_gates={},
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("3")
        await page.expect_state("artifacts_subtab", "beads")
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        pane._update_detail()
        detail = page.query_one_widget("#beads-detail", Markdown)
        await page.wait_for(lambda _state: "/sase_new_task" in detail.source)
        assert "TaskTriage" in detail.source
        await wait_for_svg_contains(page, "No beads yet")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_beads_empty_120x40",
            title="ACE Artifacts - Beads empty",
        )
