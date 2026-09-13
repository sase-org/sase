"""Headless Pilot navigation tests for the standalone ``SasePager`` app."""

from __future__ import annotations

from typing import Any

import pytest
from textual.widgets import Static

from sase.pager._help import PagerHelpScreen
from sase.pager._line_mark import LineMark, reading_scroll_y
from sase.pager.app import PagerExit, SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from sase.pager.resolve import LinkTarget, LinkTargetKind

from ._app_helpers import (
    body_scroll,
    lines,
    long_document,
    multi_section_document,
    pager_screen,
)


def _named_file(name: str, count: int = 80) -> PagerDocument:
    section = PagerSection(
        identity=f"file:/tmp/{name}",
        title=name,
        kind="file",
        body=lines("line", count),
    )
    return PagerDocument(sections=(section,), title=name, origin=PagerOrigin.FILE)


async def test_q_closes_the_pager_with_a_pager_exit() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("q")
        await pilot.pause()

    assert app.return_value == PagerExit()


async def test_backspace_on_empty_trail_exits_with_exhausted_marker() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("backspace")
        await pilot.pause()

    assert app.return_value == PagerExit(trail_exhausted=True)


async def test_escape_also_closes_the_pager() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("escape")
        await pilot.pause()

    assert app.return_value == PagerExit()


async def test_j_and_k_scroll_one_line_at_a_time() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = body_scroll(app)
        await pilot.press("j")
        await pilot.pause()
        assert scroll.scroll_y == 1

        await pilot.press("j")
        await pilot.pause()
        assert scroll.scroll_y == 2

        await pilot.press("k")
        await pilot.pause()
        assert scroll.scroll_y == 1


async def test_ctrl_d_and_ctrl_u_scroll_half_a_page() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = body_scroll(app)
        half_page = scroll.size.height // 2

        await pilot.press("ctrl+d")
        await pilot.pause()
        assert scroll.scroll_y == half_page

        await pilot.press("ctrl+u")
        await pilot.pause()
        assert scroll.scroll_y == 0


async def test_g_and_shift_g_jump_to_top_and_bottom() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = body_scroll(app)

        await pilot.press("G")
        await pilot.pause()
        assert scroll.scroll_y == scroll.max_scroll_y
        assert scroll.max_scroll_y > 0

        await pilot.press("g")
        await pilot.pause()
        assert scroll.scroll_y == 0


async def test_ctrl_n_and_ctrl_p_scroll_to_the_next_and_previous_section() -> None:
    app = SasePager(multi_section_document())
    async with app.run_test(size=(80, 10)) as pilot:
        screen = pager_screen(app)
        scroll = body_scroll(app)
        assert screen._body is not None
        offsets = screen._body.section_offsets

        await pilot.press("ctrl+n")
        await pilot.pause()
        assert scroll.scroll_y == offsets[1]

        await pilot.press("ctrl+n")
        await pilot.pause()
        assert scroll.scroll_y == offsets[2]

        # the last section: ctrl+n goes to the end rather than doing nothing.
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert scroll.scroll_y == scroll.max_scroll_y

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert scroll.scroll_y == offsets[1]

        await pilot.press("ctrl+p")
        await pilot.pause()
        assert scroll.scroll_y == offsets[0]


async def test_ctrl_n_is_inert_for_a_single_section_document() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = body_scroll(app)
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert scroll.scroll_y == 0


async def test_question_mark_opens_and_closes_the_help_screen() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, PagerHelpScreen)

        await pilot.press("q")
        await pilot.pause()
        assert not isinstance(app.screen, PagerHelpScreen)
        assert app.return_value is None


async def test_slash_search_highlights_and_scrolls_to_a_match() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = body_scroll(app)
        await pilot.press("slash")
        await pilot.pause()
        for character in "line 60":
            await pilot.press(character)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert scroll.scroll_y > 0
        command = pager_screen(app).query_one("#pager-search-command", Static)
        assert "hidden" not in command.classes

        await pilot.press("escape")
        await pilot.pause()
        assert "hidden" in command.classes


async def test_footer_shows_entity_nav_only_for_multi_section_documents() -> None:
    single = SasePager(long_document())
    async with single.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        footer = pager_screen(pilot.app).query_one("#pager-footer", Static)
        assert "^N/^P" not in footer.visual.plain  # type: ignore[attr-defined]

    multi = SasePager(multi_section_document())
    async with multi.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        footer = pager_screen(pilot.app).query_one("#pager-footer", Static)
        assert "^N/^P" in footer.visual.plain  # type: ignore[attr-defined]


def _expected_reading_y(screen: Any, *, start_line: int, end_line: int) -> int:
    assert screen._body is not None
    start_row = screen._body.section_line_rows[0][start_line - 1]
    end_row = screen._last_row_for_section_line(0, end_line)
    assert end_row is not None
    scroll = screen._body_scroll()
    return reading_scroll_y(
        start_row=start_row,
        end_row=end_row,
        viewport_height=max(int(scroll.size.height), 1),
        max_scroll_y=int(scroll.max_scroll_y),
    )


async def test_link_target_scroll_range_sets_mark_and_reading_position() -> None:
    app = SasePager(_named_file("source.py"))
    target = _named_file("resolve.py")
    async with app.run_test(size=(80, 10)) as pilot:
        screen = pager_screen(app)
        scroll = body_scroll(app)
        await pilot.pause()
        screen._apply_resolution(
            "resolve.py:12-20",
            LinkTarget(
                kind=LinkTargetKind.DOCUMENT,
                document=target,
                scroll_line=12,
                scroll_end_line=20,
            ),
            intent="follow",
        )
        await pilot.pause()

        assert screen.document is target
        assert screen._goto_mark == LineMark(0, 12, 20)
        assert int(scroll.scroll_y) == _expected_reading_y(
            screen, start_line=12, end_line=20
        )
        assert screen._body is not None
        rendered = list(screen._body.renderable.renderables)[0]
        rows = rendered.plain.split("\n")
        assert rows[10].startswith("11│ ")
        assert rows[11].startswith("12┃ ")
        assert rows[19].startswith("20┃ ")
        assert rows[20].startswith("21│ ")
        assert screen._trail_snapshot().current.short_label == "resolve.py:12–20"


async def test_past_eof_line_clamps_with_information_toast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str, str]] = []

    def notify(message: str, *, severity: str = "information", **_kwargs: Any) -> None:
        notifications.append((message, severity))

    app = SasePager(_named_file("source.py"))
    target = _named_file("resolve.py")
    async with app.run_test(size=(80, 10)) as pilot:
        screen = pager_screen(app)
        monkeypatch.setattr(screen, "notify", notify)
        await pilot.pause()
        screen._apply_resolution(
            "resolve.py:9999",
            LinkTarget(
                kind=LinkTargetKind.DOCUMENT,
                document=target,
                scroll_line=9999,
            ),
            intent="follow",
        )
        await pilot.pause()

        assert screen._goto_mark == LineMark(0, 80, 80)
        assert (
            "resolve.py has 80 lines — showing line 80.",
            "information",
        ) in notifications


async def test_past_eof_end_line_clamps_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str, str]] = []

    def notify(message: str, *, severity: str = "information", **_kwargs: Any) -> None:
        notifications.append((message, severity))

    app = SasePager(_named_file("source.py"))
    target = _named_file("resolve.py")
    async with app.run_test(size=(80, 10)) as pilot:
        screen = pager_screen(app)
        monkeypatch.setattr(screen, "notify", notify)
        await pilot.pause()
        screen._apply_resolution(
            "resolve.py:10-9999",
            LinkTarget(
                kind=LinkTargetKind.DOCUMENT,
                document=target,
                scroll_line=10,
                scroll_end_line=9999,
            ),
            intent="follow",
        )
        await pilot.pause()

        assert screen._goto_mark == LineMark(0, 10, 80)
        assert not any(
            "showing line" in message for message, _severity in notifications
        )


async def test_back_and_forward_restore_the_line_mark() -> None:
    app = SasePager(_named_file("source.py"))
    landed = _named_file("resolve.py")
    other = _named_file("other.py")
    async with app.run_test(size=(80, 10)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        screen._apply_resolution(
            "resolve.py:12-20",
            LinkTarget(
                kind=LinkTargetKind.DOCUMENT,
                document=landed,
                scroll_line=12,
                scroll_end_line=20,
            ),
            intent="follow",
        )
        await pilot.pause()
        screen._apply_resolution(
            "other.py",
            LinkTarget(kind=LinkTargetKind.DOCUMENT, document=other),
            intent="follow",
        )
        await pilot.pause()

        assert screen.document is other
        assert screen._goto_mark is None
        assert any(
            entry.short_label == "resolve.py:12–20"
            for entry in screen._trail_snapshot().entries
            if entry.state == "back"
        )

        await pilot.press("backspace")
        await pilot.pause()

        assert screen.document is landed
        assert screen._goto_mark == LineMark(0, 12, 20)
        assert screen._trail_snapshot().current.short_label == "resolve.py:12–20"

        await pilot.press("tab")
        await pilot.pause()

        assert screen.document is other
        assert screen._goto_mark is None
