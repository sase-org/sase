"""Headless Pilot tests for the pager's ``;`` / ``:`` go-to-line prompt."""

from __future__ import annotations

from typing import Any

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.pager.app import SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.screen import PagerScreen


def _lines(prefix: str, count: int) -> str:
    return "\n".join(f"{prefix} {index}" for index in range(count)) + "\n"


def _long_document() -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/long.py",
        title="long.py",
        kind="file",
        body=_lines("line", 80),
    )
    return PagerDocument(sections=(section,), title="one file", origin=PagerOrigin.FILE)


def _link_document(count: int) -> PagerDocument:
    body = "\n".join(f"https://example.test/{index}" for index in range(count)) + "\n"
    section = PagerSection(
        identity="file:/tmp/links.txt",
        title="links.txt",
        kind="file",
        body=body,
    )
    return PagerDocument(sections=(section,), title="links", origin=PagerOrigin.FILE)


def _empty_document() -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/empty.py",
        title="empty.py",
        kind="file",
        body="",
    )
    return PagerDocument(sections=(section,), title="empty.py", origin=PagerOrigin.FILE)


def _pager_screen(app: SasePager) -> PagerScreen:
    screen = app.screen
    assert isinstance(screen, PagerScreen)
    return screen


def _body_scroll(app: SasePager) -> VerticalScroll:
    return _pager_screen(app).query_one("#pager-body-scroll", VerticalScroll)


def _goto_command(app: SasePager) -> Static:
    return _pager_screen(app).query_one("#pager-goto-command", Static)


async def test_semicolon_and_colon_both_open_the_goto_prompt() -> None:
    for key in ("semicolon", "colon"):
        app = SasePager(_long_document())
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            command = _goto_command(app)
            assert "hidden" in command.classes
            await pilot.press(key)
            await pilot.pause()
            assert "hidden" not in command.classes
            assert "line 1-80" in command.visual.plain  # type: ignore[attr-defined]
            await pilot.press("escape")
            await pilot.pause()
            assert "hidden" in command.classes
            assert app.return_value is None


async def test_goto_line_enter_scrolls_to_the_marked_row() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        screen = _pager_screen(app)
        scroll = _body_scroll(app)
        await pilot.pause()
        await pilot.press("semicolon")
        for character in "42":
            await pilot.press(character)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert screen._body is not None
        assert screen._goto_mark == (0, 42)
        assert int(scroll.scroll_y) == screen._body.section_line_rows[0][41]
        assert "hidden" in _goto_command(app).classes


async def test_goto_digits_do_not_activate_labels() -> None:
    app = SasePager(_link_document(2))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = _pager_screen(app)
        await pilot.pause()
        await pilot.press("semicolon")
        await pilot.press("1")
        await pilot.pause()

        assert screen._last_activated_label is None
        assert screen._goto_digits == "1"
        assert screen._goto_active is True


async def test_goto_escape_cancels_without_closing_the_pager() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("semicolon")
        await pilot.press("escape")
        await pilot.pause()

        assert "hidden" in _goto_command(app).classes
        assert app.return_value is None
        assert _pager_screen(app)._goto_active is False


async def test_goto_enter_out_of_range_keeps_the_prompt_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str, str]] = []

    def notify(message: str, *, severity: str = "information", **_kwargs: Any) -> None:
        notifications.append((message, severity))

    app = SasePager(_long_document())
    monkeypatch.setattr(app, "notify", notify)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = _pager_screen(app)
        await pilot.pause()
        await pilot.press("semicolon")
        await pilot.press("0")
        await pilot.press("enter")
        await pilot.pause()

        assert screen._goto_active is True
        assert "hidden" not in _goto_command(app).classes
        assert any(severity == "warning" for _message, severity in notifications)


async def test_goto_backspace_on_empty_cancels() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("semicolon")
        await pilot.press("backspace")
        await pilot.pause()

        assert "hidden" in _goto_command(app).classes
        assert _pager_screen(app)._goto_active is False
        assert app.return_value is None


async def test_goto_empty_document_notifies_without_opening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str, str]] = []

    def notify(message: str, *, severity: str = "information", **_kwargs: Any) -> None:
        notifications.append((message, severity))

    app = SasePager(_empty_document())
    monkeypatch.setattr(app, "notify", notify)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("semicolon")
        await pilot.pause()

        assert "hidden" in _goto_command(app).classes
        assert ("Nothing to jump to.", "warning") in notifications


async def test_slash_is_consumed_while_the_goto_prompt_is_open() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 24)) as pilot:
        screen = _pager_screen(app)
        await pilot.pause()
        await pilot.press("semicolon")
        await pilot.press("slash")
        await pilot.pause()

        search = screen.query_one("#pager-search-command", Static)
        assert "hidden" not in _goto_command(app).classes
        assert "hidden" in search.classes
        assert screen._search.mode == "off"
