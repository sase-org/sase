"""ACE PNG visual snapshot coverage for Artifacts → Beads."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget
from tests.ace.tui._artifacts_beads_helpers import snapshot as _snapshot
from tests.ace.tui._artifacts_plans_helpers import _choices
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_artifacts_beads_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    snapshot = _snapshot(tmp_path)
    snapshot = replace(
        snapshot,
        plan_links={("alpha", "alpha-1"): "/workspace/alpha--plans/202608/beads.md"},
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
        assert pane.select_entry_target(
            ArtifactEntryTarget(pane_id="beads", parts=("alpha", "epic", "alpha-1"))
        )
        await page.press("l")
        await page.wait_for(
            lambda _state: (
                not pane._epic_fold_registry.is_collapsed(("alpha", "alpha-1"))
            )
        )
        pane._update_detail()
        await wait_for_svg_contains(page, "Build bead browsing")
        await wait_for_visual_idle(page)

        for token in ("Tasks", "Epics", "awaiting triage", "-status:closed"):
            assert_page_svg_contains(page, token)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_beads_populated_120x40",
            title="ACE Artifacts - Beads populated",
        )
