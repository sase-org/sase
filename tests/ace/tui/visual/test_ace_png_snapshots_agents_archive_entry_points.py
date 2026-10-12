"""ACE PNG snapshots for the Inbox Archive shelf and empty-query bridge."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._archive_controller import (
    init_agents_archive_controller,
)
from sase.ace.tui.actions.agents._archive_shelf import sync_archive_shelf
from sase.ace.tui.models.agent_archive_controller import ArchiveShelfSnapshot
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.agent_archive_shelf import AgentArchiveShelf
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_column_helpers import (
    ModelCorpus,
    light_row,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    page_svg_text,
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_NOW = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)


def _live_agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="live-agent",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 10, 10, 18, 0, tzinfo=UTC),
        workflow="crs",
        raw_suffix="20261010180000",
        agent_name="live.agent",
    )


def _history() -> list[dict[str, Any]]:
    return [
        light_row("today-a", day="2026-10-10", hour=18, name="archive.today-a"),
        light_row(
            "today-b",
            day="2026-10-10",
            hour=17,
            name="archive.today-b",
            outcome="failed",
            status="FAILED",
        ),
        light_row("old-a", day="2026-10-09", hour=15, name="archive.old-a"),
    ]


async def test_agents_archive_shelf_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The filtered-empty Inbox shows the matching Archive count at the column base."""
    pin_agents_visual_now(monkeypatch, _NOW)
    patch_startup_loaders(monkeypatch, agents=[_live_agent()])

    with override_flags(agents_archive_view=True):
        async with AcePage(query='"visual"', patches=patches(), size=(160, 40)) as page:
            await wait_for_startup(page)
            await page.press("shift+tab")
            await page.expect_state("tab", "agents")
            page.app._record_explicit_agents_query_commit("status:FAILED")
            page.app._refilter_agents()
            await page.wait_for(
                lambda _state: (
                    page.app._agent_search_query == "status:FAILED"
                    and not page.app._agents
                ),
                timeout=15.0,
            )
            await wait_for_visual_idle(page)
            state = init_agents_archive_controller(page.app)
            corpus = ModelCorpus(_history())
            state.corpus = corpus
            state.status = "warm"
            state.profile = SimpleNamespace(digest="profile-1")
            state.shelf = ArchiveShelfSnapshot(
                status="ready",
                query="status:FAILED",
                total=3,
                matching=2,
            )
            state.shelf_requested_key = (
                "status:FAILED",
                state.tokens,
                id(corpus),
            )
            shelf = page.app.query_one("#agent-archive-shelf", AgentArchiveShelf)
            sync_archive_shelf(page.app)
            await wait_for_visual_idle(page)

            assert shelf.display is True
            svg_text = page_svg_text(page)
            assert "Archive" in svg_text, (
                f"shelf omitted from screen: region={shelf.region!r}, "
                f"size={shelf.size!r}, container="
                f"{page.app.query_one('#agent-list-container').size!r}, "
                f"list={page.app.query_one('#agent-list-panel').size!r}, "
                f"render={shelf.render().plain!r}"
            )
            assert_page_svg_contains(page, "2 matches this filter")

            ace_png_visual.assert_page_png(
                page,
                "agents_archive_shelf_empty_inbox_160x40",
                title="ACE Agents Archive shelf with empty Inbox",
            )


async def test_agents_archive_query_bridge_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A query-hidden Inbox result points to matching Archive runs."""
    pin_agents_visual_now(monkeypatch, _NOW)
    patch_startup_loaders(monkeypatch, agents=[_live_agent()])

    with override_flags(agents_archive_view=True):
        async with AcePage(query='"visual"', patches=patches(), size=(160, 40)) as page:
            await wait_for_startup(page)
            await page.press("shift+tab")
            await page.expect_state("tab", "agents")
            page.app._record_explicit_agents_query_commit("status:FAILED")
            page.app._refilter_agents()
            await page.wait_for(
                lambda _state: (
                    page.app._agent_search_query == "status:FAILED"
                    and not page.app._agents
                ),
                timeout=15.0,
            )
            state = init_agents_archive_controller(page.app)
            state.shelf = ArchiveShelfSnapshot(
                status="ready",
                query="status:FAILED",
                total=3,
                matching=2,
                rows=tuple(_history()[:2]),
            )
            sync_archive_shelf(page.app)
            detail = page.app.query_one("#agent-detail-panel")
            assert page.app._show_active_tab_empty_state(detail)
            await wait_for_visual_idle(page)

            text = page_svg_text(page)
            assert "Archive" in text
            assert "matches this filter" in text or "match this filter" in text
            assert "archive.today-a" in text
            assert_page_svg_contains(page, "previous filter")

            ace_png_visual.assert_page_png(
                page,
                "agents_archive_query_bridge_160x40",
                title="ACE Agents empty query Archive bridge",
            )
