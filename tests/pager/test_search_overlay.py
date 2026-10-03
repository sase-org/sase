"""Viewport-proportional incremental search overlay tests.

The pager hosts the shared ``VimSearchController`` through the optional
``vim_search_paint_matches`` hook, so a keystroke hands over sorted match
spans instead of rebuilding a styled copy of the whole corpus. Only
visible rows are materialized per keystroke. These tests prove the lazy
rows equal the legacy full-text overlay row-for-row, and that typing
stays viewport-bound without building a full-corpus ``Text``.
"""

from __future__ import annotations

import pytest
from rich.text import Text

from sase.ace.testing.wait import wait_for
from sase.ace.tui.widgets.vim_search_controller import (
    CURRENT_MATCH_STYLE,
    MATCH_STYLE,
)
from sase.pager._body_lines import (
    build_span_index,
    logical_line_end,
    logical_line_starts,
    slice_styled_line,
)
from sase.pager._layout import search_corpus, styled_search_base
from sase.pager.app import SasePager
from sase.pager.document import (
    PagerDocument,
    PagerOrigin,
    PagerSection,
    RawSourceSpec,
)
from tests.pager._app_helpers import body_scroll, pager_screen


def _section(title: str, body: str) -> PagerSection:
    return PagerSection(
        identity=f"file:/tmp/{title}", title=title, kind="file", body=body
    )


def _link_document() -> PagerDocument:
    body = (
        "see src/sase/pager/app.py and https://example.test/x here\n"
        "second line with needle\n"
        "third needle line needle again\n"
        "\n"
        "trailing words here\n"
    )
    return PagerDocument(
        sections=(_section("links.txt", body),),
        title="links",
        origin=PagerOrigin.FILE,
    )


def _multi_section_document() -> PagerDocument:
    return PagerDocument(
        sections=(
            PagerSection(
                identity="file:/tmp/a.py",
                title="a.py",
                kind="file",
                body="def hello():\n    return needle_one\n",
                raw_source=RawSourceSpec(language="python", eligible=True),
            ),
            PagerSection(
                identity="file:/tmp/b.txt",
                title="b.txt",
                kind="file",
                body="see https://example.test/x and needle_two here\nsecond line\n",
            ),
            PagerSection(
                identity="file:/tmp/empty.txt",
                title="empty.txt",
                kind="file",
                body="",
            ),
        ),
        title="multi",
        origin=PagerOrigin.FILE,
    )


def _legacy_rows(view: object, spans: tuple, current_index: int | None) -> list[Text]:
    """Rebuild the pre-hook overlay rows: one styled copy, sliced per line."""
    document = view.document  # type: ignore[attr-defined]
    base = styled_search_base(
        document,
        prepared_sections=view._prepared_section_texts(),  # type: ignore[attr-defined]
        dangling_refs=view._dangling_refs.keys(),  # type: ignore[attr-defined]
        is_dangling=view._is_target_dangling,  # type: ignore[attr-defined]
        surface=view._search_surface(),  # type: ignore[attr-defined]
    )
    assert base.plain == search_corpus(document)
    body = base.copy()
    for start, end in spans:
        if end > start:
            body.stylize(MATCH_STYLE, start, end)
    if current_index is not None and 0 <= current_index < len(spans):
        start, end = spans[current_index]
        if end > start:
            body.stylize(CURRENT_MATCH_STYLE, start, end)
    starts = logical_line_starts(body.plain)
    index = build_span_index(body)
    return [
        slice_styled_line(
            body, starts[row], logical_line_end(starts, row, body.plain), index=index
        )
        for row in range(len(starts))
    ]


def _signature(row: Text) -> tuple:
    return (
        row.plain,
        [(span.start, span.end, str(span.style)) for span in row.spans],
    )


def _assert_rows_equal(view: object, spans: tuple, current_index: int | None) -> int:
    legacy = _legacy_rows(view, spans, current_index)
    assert len(legacy) == view._search_match_lines  # type: ignore[attr-defined]
    for row in range(len(legacy)):
        assert _signature(view.row_text(row)) == _signature(legacy[row]), f"row {row}"
    return len(legacy)


async def _type_query(pilot: object, query: str) -> None:
    for character in query:
        await pilot.press(character)  # type: ignore[attr-defined]
        await pilot.pause()  # type: ignore[attr-defined]


@pytest.mark.parametrize("query", ["needle", "e", "zzz-nomatch"])
async def test_lazy_rows_equal_legacy_overlay_for_typing_queries(query: str) -> None:
    app = SasePager(_link_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        view = pager_screen(app).focused_view
        await pilot.press("slash")
        await pilot.pause()
        await _type_query(pilot, query)
        controller = view._search
        assert controller.mode == "typing"
        selection = controller.current_selection
        total = _assert_rows_equal(
            view,
            tuple(controller.match_spans),
            selection.index if selection is not None else None,
        )
        assert total == 5


async def test_lazy_rows_cover_rule_rows_syntax_and_empty_sections() -> None:
    app = SasePager(_multi_section_document())
    async with app.run_test(size=(80, 24)) as pilot:
        view = pager_screen(app).focused_view
        await pilot.pause()
        await wait_for(pilot, lambda: bool(view._prepared_section_texts()))
        await pilot.pause()
        assert 0 in view._prepared_section_texts()
        await pilot.press("slash")
        await pilot.pause()
        await _type_query(pilot, "needle")
        controller = view._search
        selection = controller.current_selection
        total = _assert_rows_equal(
            view,
            tuple(controller.match_spans),
            selection.index if selection is not None else None,
        )
        # Two body lines + rule (a.py), two body lines + rule (b.txt),
        # one empty body line + rule (empty.txt).
        assert total == 7


async def test_lazy_rows_follow_repeats_past_the_wrap() -> None:
    app = SasePager(_link_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        view = pager_screen(app).focused_view
        await pilot.press("slash")
        await pilot.pause()
        await _type_query(pilot, "needle")
        await pilot.press("enter")
        await pilot.pause()
        controller = view._search
        assert controller.mode == "committed"
        total_matches = len(controller.match_spans)
        assert total_matches == 3
        for _ in range(total_matches + 2):
            controller.repeat()
            await pilot.pause()
            selection = controller.current_selection
            assert selection is not None
            _assert_rows_equal(view, tuple(controller.match_spans), selection.index)
        controller.repeat(reverse=True)
        await pilot.pause()
        selection = controller.current_selection
        assert selection is not None
        _assert_rows_equal(view, tuple(controller.match_spans), selection.index)


async def test_typing_repaints_at_most_a_viewport_without_a_full_corpus_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "".join(
        f"line {index:06d} with some trailing words\n" for index in range(20_000)
    )
    document = PagerDocument(
        sections=(_section("big.txt", body),), title="big", origin=PagerOrigin.FILE
    )
    app = SasePager(document)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        view = pager_screen(app).focused_view
        scroll = body_scroll(app)
        viewport = max(int(scroll.size.height), 1)
        assert viewport > 0
        await pilot.press("slash")
        await pilot.pause()
        scroll.scroll_to(y=1000, animate=False, immediate=True)
        await pilot.pause()
        view._search_rows_painted = 0
        view._search_base_lines_built = 0

        import sase.pager._screen_search as search_module

        full_text_builds = []
        original = search_module.styled_search_base

        def _counting(*args: object, **kwargs: object) -> Text:
            full_text_builds.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(search_module, "styled_search_base", _counting)
        await pilot.press("e")
        await pilot.pause()

        assert full_text_builds == []
        assert view._search_rows_painted <= viewport
        assert view._search_base_lines_built <= viewport


async def test_search_exit_releases_match_state() -> None:
    app = SasePager(_link_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        view = pager_screen(app).focused_view
        scroll = body_scroll(app)
        await pilot.press("slash")
        await pilot.pause()
        await _type_query(pilot, "needle")
        assert scroll.match_active
        view._search.exit(restore_scroll=False, refresh=False)
        await pilot.pause()
        assert not scroll.match_active
        assert view._search_match_spans == ()
        assert view._search_map is None
        assert view._search.corpus == ""
