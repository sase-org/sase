"""Headless Pilot navigation tests for the standalone ``SasePager`` app."""

from __future__ import annotations

from textual.widgets import Static

from sase.pager._help import PagerHelpScreen
from sase.pager.app import PagerExit, SasePager

from ._app_helpers import (
    body_scroll,
    long_document,
    multi_section_document,
    pager_screen,
)


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
