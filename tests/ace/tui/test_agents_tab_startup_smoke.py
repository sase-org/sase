"""Textual startup smoke coverage for the Agents tab."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.agent_list import AgentList
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    agents,
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
)


@pytest.mark.asyncio
async def test_startup_on_agents_tab_renders_loaded_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starting directly on Agents keeps the first async projection populated."""
    patch_startup_loaders(monkeypatch, agents=agents())

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        widget = page.query_one_widget("#agent-list-panel", AgentList)
        assert [agent.cl_name for agent in widget._agents] == [
            "visual-plan",
            "visual-code",
        ]
