"""Headless Pilot history tests for the standalone ``SasePager`` app."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Static

from sase.pager.app import SasePager
from sase.pager.resolve import LinkTarget, LinkTargetKind

from ._app_helpers import (
    body_scroll,
    long_link_source_document,
    pager_screen,
    searchable_link_source_document,
    target_document,
)


async def test_follow_back_and_forward_restore_the_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = target_document()
    monkeypatch.setattr(
        "sase.pager.screen.resolve_ref",
        lambda ref, **_kwargs: LinkTarget(
            kind=LinkTargetKind.DOCUMENT,
            document=target,
        ),
    )
    source = long_link_source_document(Path("/tmp/target.py"))
    app = SasePager(source)
    async with app.run_test(size=(80, 10)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        scroll = body_scroll(app)
        trail = screen.query_one("#pager-trail", Static)
        footer = screen.query_one("#pager-footer", Static)
        scroll.scroll_to(y=12, animate=False, immediate=True)
        screen._update_subject()
        await pilot.pause()

        assert "hidden" in trail.classes

        await pilot.press("0")
        await pilot.pause(0.1)
        await pilot.pause(0.1)

        assert screen.document is target
        assert screen._back_trail
        assert "hidden" not in trail.classes
        assert "⌫/^O back" in footer.visual.plain  # type: ignore[attr-defined]

        await pilot.press("backspace")
        await pilot.pause()

        assert screen.document is source
        assert int(scroll.scroll_y) == 12
        assert not screen._back_trail
        assert screen._forward_trail
        assert "hidden" in trail.classes
        assert "^I forward" in footer.visual.plain  # type: ignore[attr-defined]

        await pilot.press("ctrl+i")
        await pilot.pause()

        assert screen.document is target
        assert screen._back_trail
        assert not screen._forward_trail


async def test_back_restores_committed_search_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = target_document()
    source = searchable_link_source_document(Path("/tmp/target.py"))
    app = SasePager(source)
    async with app.run_test(size=(80, 10)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        scroll = body_scroll(app)
        await pilot.press("slash")
        for character in "needle":
            await pilot.press(character)
        await pilot.press("enter")
        await pilot.pause()

        assert screen._search.mode == "committed"
        assert screen._search.last_search == ("needle", "forward")
        source_scroll_y = int(scroll.scroll_y)
        assert source_scroll_y > 0

        screen._apply_resolution(
            "/tmp/target.py",
            LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target),
            intent="follow",
        )
        await pilot.pause()

        assert screen.document is target
        assert screen._search.mode == "off"

        await pilot.press("ctrl+o")
        await pilot.pause()

        command = screen.query_one("#pager-search-command", Static)
        assert screen.document is source
        assert int(scroll.scroll_y) == source_scroll_y
        assert screen._search.mode == "committed"
        assert screen._search.last_search == ("needle", "forward")
        assert "hidden" not in command.classes
