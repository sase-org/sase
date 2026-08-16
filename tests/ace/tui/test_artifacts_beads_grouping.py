"""Shared-registry epic fold behavior for the Artifacts Beads pane."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from tests.ace.tui._artifacts_beads_helpers import snapshot


@pytest.mark.asyncio
async def test_new_epics_start_collapsed_and_toggle_survives_reload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = snapshot(tmp_path, project=None)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: value,
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press("3")
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)

        # Default-collapsed on first load.
        assert pane._epic_fold_registry.is_collapsed(("alpha", "alpha-1"))
        assert ("alpha", "alpha-1") not in pane._expanded_epic_keys()

        pane.select_entry_target(
            next(t for t in pane.entry_targets() if t.parts[1] == "epic")
        )
        pane.set_selected_epic_expanded(True)
        assert not pane._epic_fold_registry.is_collapsed(("alpha", "alpha-1"))

        # A reload with the same epic must not reset the user's choice.
        pane._snapshot = value
        pane._refresh_options(preferred_id=pane._selected_option_id())
        assert not pane._epic_fold_registry.is_collapsed(("alpha", "alpha-1"))


@pytest.mark.asyncio
async def test_fold_state_is_pruned_when_an_epic_disappears_and_reseeded_on_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = snapshot(tmp_path, project=None)
    state = {"snapshot": value}
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: state["snapshot"],
    )

    async with AcePage(initial_tab="patches") as page:
        await page.press("3")
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is value)

        pane.select_entry_target(
            next(t for t in pane.entry_targets() if t.parts[1] == "epic")
        )
        pane.set_selected_epic_expanded(True)
        assert not pane._epic_fold_registry.is_collapsed(("alpha", "alpha-1"))

        # The epic drops out of the next snapshot entirely.
        without_epic = replace(value, epics=(), phases_by_epic={})
        state["snapshot"] = without_epic
        pane._snapshot = without_epic
        pane._refresh_options()
        assert ("alpha", "alpha-1") not in pane._known_epic_keys

        # It reappears later — treated as newly-seen, so it's collapsed again
        # rather than silently inheriting the stale "expanded" choice.
        state["snapshot"] = value
        pane._snapshot = value
        pane._refresh_options()
        assert pane._epic_fold_registry.is_collapsed(("alpha", "alpha-1"))
