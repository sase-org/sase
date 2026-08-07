"""Pilot coverage: cross-tab ChangeSpec jumps land on the Artifacts PRs sub-tab.

Regression coverage for the migration miss where switching to the Artifacts
tab left whichever sub-tab was last visible (``commits`` by default) instead
of the PRs pane the jump actually targets.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import DEFAULT_CHANGESPECS, AcePage, make_changespec
from sase.ace.tui.widgets import ArtifactsView
from tests.ace.tui._agents_zoom_panel_helpers import _make_agent
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
)


async def test_enter_from_agents_lands_on_prs_subtab_for_matching_changespec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """<enter> on an agent whose ChangeSpec is already in view selects PRs."""
    agent = _make_agent(
        cl_name="feature_a",
        project_file="/tmp/projects/demoproj/demoproj.sase",
    )
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await page.expect_state("agent_count", 1)

        await page.press("enter")
        await page.pause()

        await page.expect_state("tab", "changespecs")
        assert page.state["artifacts_subtab"] == "prs"
        assert page.state["selected"]["name"] == "feature_a"

        artifacts_view = page.query_one_widget("#changespecs-view", ArtifactsView)
        assert artifacts_view.current_subtab == "prs"


async def test_enter_from_agents_rewrites_query_and_lands_on_prs_subtab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the target ChangeSpec is outside the query, the swap lands on PRs."""
    target = make_changespec(
        name="chore_cleanup", file_path="/tmp/projects/otherproj/otherproj.sase"
    )
    agent = _make_agent(
        cl_name="chore_cleanup",
        project_file="/tmp/projects/otherproj/otherproj.sase",
    )
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(
        initial_tab="agents",
        changespecs=[*DEFAULT_CHANGESPECS, target],
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("agent_count", 1)

        await page.press("enter")
        await page.pause()

        await page.expect_state("tab", "changespecs")
        assert page.state["artifacts_subtab"] == "prs"
        assert page.state["query"] == "project:otherproj"
        assert page.state["selected"]["name"] == "chore_cleanup"

        artifacts_view = page.query_one_widget("#changespecs-view", ArtifactsView)
        assert artifacts_view.current_subtab == "prs"


async def test_load_saved_query_from_agents_lands_on_prs_subtab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A numbered saved-query slot loaded from Agents shows the PRs pane."""
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)

        # DEFAULT_CHANGESPECS all live under the "tmp" project directory.
        page.app._saved_queries["1"] = "project:tmp"

        page.app.action_load_saved_query_1()
        await page.pause()

        await page.expect_state("tab", "changespecs")
        assert page.state["artifacts_subtab"] == "prs"
        assert page.state["query"] == "project:tmp"

        artifacts_view = page.query_one_widget("#changespecs-view", ArtifactsView)
        assert artifacts_view.current_subtab == "prs"
