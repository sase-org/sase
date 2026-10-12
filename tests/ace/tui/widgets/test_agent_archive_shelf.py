"""Presentation for the one-line Inbox Archive shelf."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from sase.ace.tui.models.agent_archive_controller import ArchiveShelfSnapshot
from sase.ace.tui.widgets.agent_archive_shelf import AgentArchiveShelf


class _ShelfApp(App[None]):
    def compose(self) -> ComposeResult:
        yield AgentArchiveShelf()


@pytest.mark.asyncio
async def test_archive_shelf_shows_total_and_today_without_a_query() -> None:
    app = _ShelfApp()
    async with app.run_test():
        shelf = app.query_one(AgentArchiveShelf)
        shelf.set_snapshot(
            ArchiveShelfSnapshot(status="ready", total=12, today=3),
            inbox_empty=False,
            enabled=True,
        )

        assert shelf.render().plain == "◷ Archive · 12 runs · 3 today"
        assert shelf.has_class("-visible")
        assert not shelf.has_class("-empty")


@pytest.mark.asyncio
async def test_archive_shelf_shows_matching_count_and_empty_inbox_state() -> None:
    app = _ShelfApp()
    async with app.run_test():
        shelf = app.query_one(AgentArchiveShelf)
        shelf.set_snapshot(
            ArchiveShelfSnapshot(
                status="ready",
                query="status:FAILED",
                total=12,
                matching=2,
            ),
            inbox_empty=True,
            enabled=True,
        )

        assert (
            shelf.render().plain == "◷ Archive · 2 matches this filter · ⏎ / ,a search"
        )
        assert shelf.has_class("-empty")
