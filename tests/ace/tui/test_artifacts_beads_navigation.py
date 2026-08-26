"""Mounted navigation behavior for the Artifacts Beads pane."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget
from tests.ace.tui._artifacts_beads_helpers import snapshot


@pytest.mark.asyncio
async def test_selection_marks_jumps_and_reload_preserve_stable_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = snapshot(tmp_path, project=None)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        targets = pane.entry_targets()
        assert targets == (
            ArtifactEntryTarget(
                pane_id="beads", parts=("alpha", "task", "alpha-ready")
            ),
            ArtifactEntryTarget(pane_id="beads", parts=("alpha", "task", "alpha-open")),
            ArtifactEntryTarget(pane_id="beads", parts=("alpha", "epic", "alpha-1")),
        )

        assert pane.select_entry_target(targets[1])
        pane.apply_entry_marks({targets[1]})
        pane.apply_entry_jump_hints({targets[1]: "A"})
        assert pane.selected_entry_target() == targets[1]

        pane._snapshot = value
        pane._refresh_options(preferred_id=pane._selected_option_id())
        assert pane.selected_entry_target() == targets[1]

        assert pane.select_entry_target(targets[2])
        pane.set_selected_epic_expanded(True)
        assert pane.entry_targets()[-1:] == (
            ArtifactEntryTarget(pane_id="beads", parts=("alpha", "phase", "alpha-1.2")),
        )


@pytest.mark.asyncio
async def test_detail_scroll_reserves_its_gutter_so_the_width_never_oscillates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The detail pane's content width must not depend on the scrollbar.

    The Created property value fills the content width exactly, so an auto
    gutter gives one bead two stable layouts: without a scrollbar the value
    fits on one line, and with one it wraps, which adds the very line that
    keeps the scrollbar. The reserved gutter collapses that to one layout.
    """
    value = snapshot(tmp_path, project=None)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        scroll = pane.query_one("#beads-detail-scroll")

        assert scroll.styles.scrollbar_gutter == "stable"

        width_without_scrollbar = scroll.content_region.width
        scroll.show_vertical_scrollbar = True
        assert scroll.content_region.width == width_without_scrollbar
