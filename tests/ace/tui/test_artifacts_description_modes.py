"""Artifacts pane-brief description-mode helpers and application integration."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.artifacts_description import (
    ARTIFACTS_DESCRIPTION_MODE_ORDER,
    cycle_artifacts_description_mode,
    normalize_artifacts_description_mode,
)
from sase.ace.tui.widgets.artifacts.pane_brief import ArtifactsPaneBrief
from sase.ace.tui.widgets.artifacts.view import ArtifactsView


def test_cycle_artifacts_description_mode_wraps_forward() -> None:
    for index, mode in enumerate(ARTIFACTS_DESCRIPTION_MODE_ORDER):
        assert (
            cycle_artifacts_description_mode(mode, 1)
            == ARTIFACTS_DESCRIPTION_MODE_ORDER[
                (index + 1) % len(ARTIFACTS_DESCRIPTION_MODE_ORDER)
            ]
        )


def test_cycle_artifacts_description_mode_is_forward_regardless_of_direction() -> None:
    # Cycling is forward-only in the UI; the helper still honors a negative
    # direction so it stays symmetric with cycle_artifacts_split_mode.
    assert cycle_artifacts_description_mode("off", -1) == "full"
    assert cycle_artifacts_description_mode("full", -1) == "summary"


def test_normalize_artifacts_description_mode_falls_back_to_summary() -> None:
    for value in (None, "unknown", 1, True, object()):
        assert normalize_artifacts_description_mode(value) == "summary"


async def test_description_key_cycles_mode_and_toggles_display() -> None:
    async with AcePage(initial_tab="patches") as page:
        view = page.query_one_widget("#artifacts-view", ArtifactsView)
        brief = page.query_one_widget("#artifacts-pane-brief", ArtifactsPaneBrief)

        assert page.app.artifacts_description_mode == "summary"
        assert brief.display is True

        await page.press("D")
        assert page.app.artifacts_description_mode == "full"
        assert brief.display is True

        await page.press("D")
        assert page.app.artifacts_description_mode == "off"
        assert brief.display is False

        await page.press("D")
        assert page.app.artifacts_description_mode == "summary"
        assert brief.display is True
        assert view.description_mode == "summary"


async def test_description_action_scoped_to_every_artifacts_subtab() -> None:
    async with AcePage(initial_tab="patches") as page:
        view = page.query_one_widget("#artifacts-view", ArtifactsView)

        for descriptor in view.descriptors:
            page.app.current_artifacts_subtab = descriptor.id
            await page.pause()
            assert page.app.check_action("cycle_artifacts_description", ()) is True

        page.app.current_tab = "agents"
        await page.pause()
        assert page.app.check_action("cycle_artifacts_description", ()) is False
        page.app.current_tab = "axe"
        await page.pause()
        assert page.app.check_action("cycle_artifacts_description", ()) is False


async def test_toggle_attempt_view_scoped_to_agents_tab() -> None:
    async with AcePage(initial_tab="patches") as page:
        # Patches was the historical hole: toggle_attempt_view used to stay
        # available there because only non-Patch Artifacts panes were gated.
        assert page.app.check_action("toggle_attempt_view", ()) is False

        page.app.current_tab = "agents"
        await page.pause()
        assert page.app.check_action("toggle_attempt_view", ()) is True


async def test_clicking_pane_brief_cycles_forward() -> None:
    async with AcePage(initial_tab="patches") as page:
        assert page.app.artifacts_description_mode == "summary"
        await page.click("#artifacts-pane-brief", offset=(1, 0))
        await page.pause()
        assert page.app.artifacts_description_mode == "full"
