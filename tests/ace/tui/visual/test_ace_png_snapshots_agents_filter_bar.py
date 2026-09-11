"""ACE TUI PNG visual snapshots for the auto-hiding Agents FilterBar (sase-zf.4).

Covers the two states that differ from the plain agent list already snapshot
by ``test_ace_png_snapshots_agents.py``: an idle info-panel readout for a
committed query, and the bar open with its completion menu. The third
state -- hidden, no active query -- is exactly the existing
``agents_list_120x40`` golden, so it is not duplicated here.
"""

from __future__ import annotations

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.agents_filter_bar import AgentsFilterBar
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    agents,
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_agents_filter_bar_idle_readout_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A committed query renders as a highlighted readout with a match count."""
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)

        page.app._agent_search_query = "status:FAILED"
        page.app._refilter_agents()
        await page.pause()
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_filter_bar_idle_readout_120x40",
            title="ACE Agents filter bar idle readout",
        )


async def test_agents_filter_bar_editing_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The auto-hiding bar, open with its completion menu visible."""
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)

        await page.press("f")
        await page.pause()
        bar = page.query_one_widget("#agents-filter-bar", AgentsFilterBar)
        bar.open("stat")
        completion = bar.query_one(f"#{bar.COMPLETION_ID}", OptionList)
        await page.wait_for(
            lambda _state: completion.display and completion.option_count >= 1
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_filter_bar_editing_120x40",
            title="ACE Agents filter bar editing",
        )
