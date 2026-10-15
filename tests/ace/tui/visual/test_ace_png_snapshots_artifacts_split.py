"""PNG coverage for all shared Artifacts split modes."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.containers import VerticalScroll

from sase.ace.testing import AcePage
from sase.ace.tui.artifacts_split import ArtifactsSplitMode
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget
from sase.ace.tui.widgets.artifacts.view import ArtifactsView
from tests.ace.tui._artifacts_beads_helpers import snapshot as _snapshot
from tests.ace.tui._artifacts_plans_helpers import _choices
from tests.ace.tui.visual._ace_top_bar_png_snapshot_helpers import (
    wait_for_top_bar_density,
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
        await page.press(page.artifacts_digit("beads"))
        await page.expect_state("artifacts_subtab", "beads")
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.wait_for(
            lambda _state: getattr(pane, "_project_display_name", None) == "Alpha",
            timeout=15.0,
        )
        pane._update_detail()
        page.app.artifacts_split_mode = mode
        await wait_for_svg_contains(page, "Tasks")
        await wait_for_visual_idle(page)
        if size == (120, 40):
            await wait_for_top_bar_density(page, expected="full")
            await wait_for_visual_idle(page)

        artifacts_view = page.app.query_one("#artifacts-view", ArtifactsView)
        detail_scroll = pane.query_one("#beads-detail-scroll", VerticalScroll)
        await page.wait_for(
            lambda _state: (
                artifacts_view.split_mode == mode
                and detail_scroll.region.width > 0
                and detail_scroll.region.height > 0
            )
        )
        detail_scroll.scroll_to(y=0, animate=False)
        await page.wait_for(lambda _state: detail_scroll.scroll_y == 0)
        if snapshot_name == "artifacts_split_selected_wide_120x40":
            # This layout fixture covers split geometry and selected content;
            # scrollbar behavior is covered by the other scrolling snapshots.
            detail_scroll.show_vertical_scrollbar = False
            await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title=f"ACE Artifacts - {mode.title()} split",
        )


@pytest.mark.parametrize(
    ("mode", "size", "snapshot_name"),
    (
        ("narrow", (120, 40), "artifacts_split_selected_narrow_120x40"),
        ("even", (120, 40), "artifacts_split_selected_even_120x40"),
        ("wide", (120, 40), "artifacts_split_selected_wide_120x40"),
        ("narrow", (80, 24), "artifacts_split_selected_narrow_80x24"),
    ),
)
async def test_artifacts_split_mode_selected_detail_png_snapshot(
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
        await page.press(page.artifacts_digit("beads"))
        await page.expect_state("artifacts_subtab", "beads")
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.wait_for(
            lambda _state: getattr(pane, "_project_display_name", None) == "Alpha",
            timeout=15.0,
        )
        assert pane.select_entry_target(
            ArtifactEntryTarget(pane_id="beads", parts=("alpha", "task", "alpha-ready"))
        )
        pane._update_detail()
        page.app.artifacts_split_mode = mode
        await wait_for_svg_contains(page, "Ready for triage")
        await wait_for_svg_contains(page, "snooze")
        await wait_for_visual_idle(page)
        if size == (120, 40):
            await wait_for_top_bar_density(page, expected="full")
            await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title=f"ACE Artifacts - {mode.title()} split selected detail",
        )
