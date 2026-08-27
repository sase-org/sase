"""Headless Pilot key-binding tests for the standalone ``SasePager`` app."""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.pager._help import PagerHelpScreen
from sase.pager.app import PagerExit, SasePager
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection


def _lines(prefix: str, count: int) -> str:
    return "\n".join(f"{prefix} {index}" for index in range(count)) + "\n"


def _long_document(title: str = "one file") -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/long.py",
        title="long.py",
        kind="file",
        body=_lines("line", 80),
    )
    return PagerDocument(sections=(section,), title=title, origin=PagerOrigin.FILE)


def _multi_section_document() -> PagerDocument:
    sections = tuple(
        PagerSection(
            identity=f"file:/tmp/{name}.py",
            title=f"{name}.py",
            kind="file",
            body=_lines(name, 30),
        )
        for name in ("alpha", "beta", "gamma")
    )
    return PagerDocument(sections=sections, title="3 files", origin=PagerOrigin.FILE)


def _link_document(count: int) -> PagerDocument:
    body = "\n".join(f"https://example.test/{index}" for index in range(count)) + "\n"
    section = PagerSection(
        identity="file:/tmp/links.txt",
        title="links.txt",
        kind="file",
        body=body,
    )
    return PagerDocument(sections=(section,), title="links", origin=PagerOrigin.FILE)


def _body_scroll(app: SasePager) -> VerticalScroll:
    return app.query_one("#pager-body-scroll", VerticalScroll)


async def test_q_closes_the_pager_with_a_pager_exit() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("q")
        await pilot.pause()

    assert app.return_value == PagerExit()


async def test_escape_also_closes_the_pager() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("escape")
        await pilot.pause()

    assert app.return_value == PagerExit()


async def test_j_and_k_scroll_one_line_at_a_time() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = _body_scroll(app)
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
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = _body_scroll(app)
        half_page = scroll.size.height // 2

        await pilot.press("ctrl+d")
        await pilot.pause()
        assert scroll.scroll_y == half_page

        await pilot.press("ctrl+u")
        await pilot.pause()
        assert scroll.scroll_y == 0


async def test_g_and_shift_g_jump_to_top_and_bottom() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = _body_scroll(app)

        await pilot.press("G")
        await pilot.pause()
        assert scroll.scroll_y == scroll.max_scroll_y
        assert scroll.max_scroll_y > 0

        await pilot.press("g")
        await pilot.pause()
        assert scroll.scroll_y == 0


async def test_ctrl_n_and_ctrl_p_scroll_to_the_next_and_previous_section() -> None:
    app = SasePager(_multi_section_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = _body_scroll(app)
        assert app._body is not None
        offsets = app._body.section_offsets

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
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = _body_scroll(app)
        await pilot.press("ctrl+n")
        await pilot.pause()
        assert scroll.scroll_y == 0


async def test_question_mark_opens_and_closes_the_help_screen() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, PagerHelpScreen)

        await pilot.press("q")
        await pilot.pause()
        assert not isinstance(app.screen, PagerHelpScreen)
        assert app.return_value is None


async def test_slash_search_highlights_and_scrolls_to_a_match() -> None:
    app = SasePager(_long_document())
    async with app.run_test(size=(80, 10)) as pilot:
        scroll = _body_scroll(app)
        await pilot.press("slash")
        await pilot.pause()
        for character in "line 60":
            await pilot.press(character)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert scroll.scroll_y > 0
        command = app.query_one("#pager-search-command", Static)
        assert "hidden" not in command.classes

        await pilot.press("escape")
        await pilot.pause()
        assert "hidden" in command.classes


async def test_footer_shows_entity_nav_only_for_multi_section_documents() -> None:
    single = SasePager(_long_document())
    async with single.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        footer = pilot.app.query_one("#pager-footer", Static)
        assert "^N/^P" not in footer.visual.plain  # type: ignore[attr-defined]

    multi = SasePager(_multi_section_document())
    async with multi.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        footer = pilot.app.query_one("#pager-footer", Static)
        assert "^N/^P" in footer.visual.plain  # type: ignore[attr-defined]


async def test_painted_link_key_records_the_selected_label() -> None:
    app = SasePager(_link_document(2))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()

    assert app._last_activated_label is not None
    assert app._last_activated_label.hint == "1"
    assert app._last_activated_label.target.text == "https://example.test/1"


async def test_uppercase_painted_link_key_uses_event_character() -> None:
    app = SasePager(_link_document(30))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("A")
        await pilot.pause()

    assert app._last_activated_label is not None
    assert app._last_activated_label.hint == "A"


async def test_pending_prefix_is_shown_in_the_footer_and_invalid_clears_it() -> None:
    app = SasePager(_link_document(53))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("Z")
        await pilot.pause()

        footer = app.query_one("#pager-footer", Static)
        assert "Z… link" in footer.visual.plain  # type: ignore[attr-defined]
        assert app._label_pending_prefix == "Z"

        await pilot.press("x")
        await pilot.pause()

        footer = app.query_one("#pager-footer", Static)
        assert "Z… link" not in footer.visual.plain  # type: ignore[attr-defined]
        assert app._label_pending_prefix == ""
