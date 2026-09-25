"""Zoomed tribe-panel Main deck follows j/k selection (sase-17d.12.2)."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import AgentDetail
from sase.ace.tui.widgets.decks.layout import is_zoomed
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)


def _agent(name: str, suffix: str, *, tribe: str | None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/projects/demo/demo.sase",
        status="DONE",
        start_time=datetime(2026, 7, 18, 9, 0, 0),
        stop_time=datetime(2026, 7, 18, 9, 5, 0),
        raw_suffix=suffix,
        agent_name=name,
        tribe=tribe,
        pid=None,
    )


@pytest.mark.asyncio
async def test_zoomed_tribe_summary_steps_keep_zoom_and_follow_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _agent("home-zoom", "home-zoom", tribe=None)
    alpha = _agent("alpha-zoom-agent", "alpha-zoom", tribe="alpha")
    zeta = _agent("zeta-zoom-agent", "zeta-zoom", tribe="zeta")
    patch_startup_loaders(monkeypatch, agents=[home, alpha, zeta])

    async with AcePage(query='"demo"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.press("J")
        await page.wait_for(
            lambda _screen: page.app._panel_group.focused_key in {"alpha", "zeta"}
        )
        await page.press("h")
        await page.wait_for(
            lambda _screen: page.app._resolve_focused_panel() is not None
        )
        await wait_for_visual_idle(page)

        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        await page.wait_for(lambda _screen: detail._current_tribe_identity is not None)
        area = detail.deck_area
        before_layout = area.state.layout
        before_collapsed = area.state.nodes_collapsed
        first_tribe = detail._current_tribe_identity

        await page.press("Z")
        await page.pause()
        assert detail.is_deck_zoomed is True
        assert is_zoomed(area.state) is True
        assert area.state.nodes_collapsed is True
        assert detail._current_tribe_identity == first_tribe

        await page.press("j")
        await wait_for_visual_idle(page)
        await page.wait_for(
            lambda _screen: detail._current_tribe_identity not in (None, first_tribe)
        )
        assert detail.is_deck_zoomed is True
        assert is_zoomed(area.state) is True
        assert detail._current_tribe_identity != first_tribe

        await page.press("Z")
        await page.pause()
        assert detail.is_deck_zoomed is False
        assert is_zoomed(area.state) is False
        assert area.state.layout is before_layout
        assert area.state.nodes_collapsed is before_collapsed
