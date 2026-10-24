"""J/K tribe-panel cycling with the Inbox Archive shelf visible."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._archive_controller import (
    init_agents_archive_controller,
)
from sase.ace.tui.actions.agents._archive_shelf import _sync_widget
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_archive_controller import ArchiveShelfSnapshot
from sase.ace.tui.widgets import AgentList
from sase.ace.tui.widgets.agent_archive_shelf import AgentArchiveShelf
from tests.ace.tui._agent_archive_column_helpers import ModelCorpus, light_row
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)


def _agent(name: str, suffix: str, tribe: str | None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/projects/demo/demo.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 18, 9, 0, 0),
        raw_suffix=suffix,
        tribe=tribe,
        pid=100,
        agent_name=f"{name}.agent",
    )


async def test_jk_wrap_tribe_panels_past_the_visible_archive_shelf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shelf is never a J/K stop, and it stays docked at the column base."""
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _agent("default", "20260718090001", None),
            _agent("epic", "20260718090002", "epic"),
            _agent("research", "20260718090003", "research"),
        ],
    )
    async with AcePage(patches=patches(), size=(160, 40)) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await wait_for_visual_idle(page)
        app = page.app
        state = init_agents_archive_controller(app)
        corpus = ModelCorpus([light_row("old", day="2026-07-17", name="old.run")])
        state.corpus = corpus
        state.status = "warm"
        state.profile = SimpleNamespace(digest="profile-1")
        state.shelf = ArchiveShelfSnapshot(status="ready", total=1, today=0)
        state.shelf_requested_key = ("", state.tokens, id(corpus))
        _sync_widget(app)
        await wait_for_visual_idle(page)

        shelf = app.query_one("#agent-archive-shelf", AgentArchiveShelf)
        panels = list(app.query_one("#agent-list-container").query(AgentList))
        assert shelf.display is True
        assert len(app._panel_group.panel_keys) == 3
        assert all(shelf.region.y >= panel.region.bottom for panel in panels)

        assert app._panel_group.focused_idx == 0
        await page.press("J")
        await page.press("J")
        await wait_for_visual_idle(page)
        assert app._panel_group.focused_idx == 2

        await page.press("J")
        await wait_for_visual_idle(page)
        assert app._panel_group.focused_idx == 0
        assert app.focused is not shelf
        assert not shelf.has_class("-focused")

        await page.press("K")
        await wait_for_visual_idle(page)
        assert app._panel_group.focused_idx == 2
        assert app.focused is not shelf
