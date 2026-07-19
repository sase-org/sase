"""PNG snapshots for inline Agents metadata search."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.ace.tui.visual.test_ace_png_snapshots_agents_zoom import _zoom_agent

pytestmark = pytest.mark.visual


async def test_agents_metadata_search_typing_and_committed_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = _zoom_agent(tmp_path)
    agent.diff_path = None
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("agent_count", 1)
        panel = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
        await page.wait_for(
            lambda _state: (
                "zoom.snapshot.agent" in (renderable_to_text(panel.content) or "")
            ),
        )

        await page.press("slash", "z", "o", "o", "m")
        await page.wait_for(
            lambda _state: (
                page.app._agent_metadata_search.mode == "typing"
                and len(page.app._agent_metadata_search.match_spans) > 1
            ),
        )
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_metadata_search_typing_120x40",
            title="ACE agents metadata search typing",
        )

        await page.press("enter", "n")
        command = page.app.query_one("#agent-search-command", Static)
        await page.wait_for(
            lambda _state: (
                page.app._agent_metadata_search.mode == "committed"
                and "[2/" in command.render().plain
            ),
        )
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_metadata_search_committed_120x40",
            title="ACE agents metadata search committed",
        )
