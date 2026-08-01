"""Mounted navigation behavior for the Artifacts Beads pane."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
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

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("2")
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)
        targets = pane.entry_targets()
        assert targets == (
            ("bead", "alpha", "task", "alpha-ready"),
            ("bead", "alpha", "task", "alpha-open"),
            ("bead", "alpha", "epic", "alpha-1"),
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
        assert pane.entry_targets()[-2:] == (
            ("bead", "alpha", "phase", "alpha-1.1"),
            ("bead", "alpha", "phase", "alpha-1.2"),
        )
