"""ACE TUI PNG snapshots for the host-owned link-reveal lens chip."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.link_reveal import make_link_reveal, pane_canonical_query
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


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [
        ((120, 40), "link_reveal_chip_beads_120x40"),
        ((60, 30), "link_reveal_chip_beads_60x30"),
    ],
)
async def test_beads_link_reveal_chip_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    size: tuple[int, int],
    snapshot_name: str,
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
        await page.press(page.artifacts_digit("beads"))
        await page.expect_state("artifacts_subtab", "beads")
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.wait_for(
            lambda _state: getattr(pane, "_project_display_name", None) == "Alpha",
            timeout=15.0,
        )

        current = pane_canonical_query(pane)
        page.app._link_reveals["beads"] = make_link_reveal(  # type: ignore[attr-defined]
            pane_id="beads",
            ref="bead:sase-hidden.3",
            origin_source="-status:closed",
            origin_canonical="-status:closed",
            origin_target=None,
            revealed_canonical=current,
        )
        pane._update_static("#beads-info", pane._scope_text())
        await wait_for_svg_contains(page, "Revealed bead:sase-hidden.3")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title="ACE Artifacts - Beads link-reveal chip",
        )
