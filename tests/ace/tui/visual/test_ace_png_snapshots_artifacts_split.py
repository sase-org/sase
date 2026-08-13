"""PNG coverage for all shared Artifacts split modes."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.artifacts_split import ArtifactsSplitMode
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


@pytest.mark.parametrize(
    ("mode", "size", "snapshot_name"),
    (
        ("narrow", (120, 40), "artifacts_split_narrow_120x40"),
        ("even", (120, 40), "artifacts_split_even_120x40"),
        ("wide", (120, 40), "artifacts_split_wide_120x40"),
        ("narrow", (80, 24), "artifacts_split_narrow_80x24"),
    ),
)
async def test_artifacts_split_mode_png_snapshot(
    mode: ArtifactsSplitMode,
    size: tuple[int, int],
    snapshot_name: str,
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
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: snapshot,
    )

    async with AcePage(query='"visual"', patches=patches(), size=size) as page:
        await wait_for_startup(page)
        await page.press("3")
        await page.expect_state("artifacts_subtab", "beads")
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        pane._update_detail()
        page.app.artifacts_split_mode = mode
        await wait_for_svg_contains(page, "Tasks")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title=f"ACE Artifacts - {mode.title()} split",
        )
