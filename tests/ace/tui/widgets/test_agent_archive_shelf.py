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
        )

        assert shelf.render().plain == "◷ Archive · 2 match this filter · ⏎ search"
        assert shelf.has_class("-empty")


@pytest.mark.asyncio
async def test_archive_shelf_uses_matches_as_the_single_count_verb() -> None:
    app = _ShelfApp()
    async with app.run_test():
        shelf = app.query_one(AgentArchiveShelf)
        shelf.set_snapshot(
            ArchiveShelfSnapshot(
                status="ready",
                query="status:FAILED",
                total=12,
                matching=1,
            ),
            inbox_empty=True,
        )

        assert shelf.render().plain == ("◷ Archive · 1 matches this filter · ⏎ search")


@pytest.mark.asyncio
async def test_archive_shelf_blur_clears_its_temporary_focus() -> None:
    app = _ShelfApp()
    async with app.run_test():
        shelf = app.query_one(AgentArchiveShelf)
        shelf.add_class("-focused")
        app._agent_archive_shelf_focused = True  # type: ignore[attr-defined]

        shelf.on_blur(object())  # type: ignore[arg-type]

        assert app._agent_archive_shelf_focused is False  # type: ignore[attr-defined]
        assert not shelf.has_class("-focused")
