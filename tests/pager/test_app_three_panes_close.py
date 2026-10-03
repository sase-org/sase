"""Close, fit-refusal, and footer tests for three-pane ``SasePager``."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.util.pane_grid import _Geometry, _geometry
from sase.pager._screen_widgets import PagerBodyScroll
from sase.pager.app import SasePager
from sase.pager.split import PagerSplitLayout
from sase.pager.view import PagerView

from ._app_helpers import long_document, pager_screen
from ._three_panes_helpers import (
    footer_text,
    mounted_views,
    nest_main_top,
    panes_container,
)


async def test_close_pair_pane_keeps_outer_split_and_mru_focus() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await nest_main_top(pilot, app)
        closing = screen.focused_view
        assert closing is screen._views_by_id[2]
        # MRU order is (2, 1, 0): closing pane 2 focuses survivor 1.
        await pilot.press("ctrl+x")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        assert closing not in screen.views
        assert screen.focused_view is screen._views_by_id[1]
        assert screen._split_state.layout is PagerSplitLayout.BELOW
        assert screen._views_by_id[1].parent is panes_container(app)
        assert mounted_views(app) == list(screen.views)
        assert len(screen.focused_view.query("#pager-body-scroll")) == 1
        survivor = screen.focused_view
        assert survivor._body is not None and survivor._body.total_height > 0
        body = survivor.query_one("#pager-body-scroll", PagerBodyScroll)
        before = int(body.scroll_y)
        await pilot.press("j")
        await pilot.pause()
        assert int(body.scroll_y) != before


async def test_close_main_pane_leaves_the_pair() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await nest_main_top(pilot, app)
        main = screen._views_by_id[0]
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert screen.focused_view is main
        await pilot.press("q")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        assert main not in screen.views
        assert _geometry(screen._grid) is _Geometry.C2
        # MRU order was (0, 2, 1): the survivor focus is pane 2.
        assert screen.focused_view is screen._views_by_id[2]
        assert mounted_views(app) == list(screen.views)
        assert len(screen.focused_view.query("#pager-body-scroll")) == 1
        survivor = screen.focused_view
        assert survivor._body is not None and survivor._body.total_height > 0
        body = survivor.query_one("#pager-body-scroll", PagerBodyScroll)
        before = int(body.scroll_y)
        await pilot.press("j")
        await pilot.pause()
        assert int(body.scroll_y) != before


async def test_close_last_of_three_keeps_mounted_scrolling_survivor() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await nest_main_top(pilot, app)
        await pilot.press("q")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        assert mounted_views(app) == list(screen.views)
        await pilot.press("q")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 1
        survivor = screen.views[0]
        assert survivor.parent is panes_container(app)
        assert mounted_views(app) == [survivor]
        assert len(survivor.query("#pager-body-scroll")) == 1
        assert screen._split_state.layout is PagerSplitLayout.SINGLE
        assert survivor._body is not None and survivor._body.total_height > 0
        body = survivor.query_one("#pager-body-scroll", PagerBodyScroll)
        before = int(body.scroll_y)
        await pilot.press("j")
        await pilot.pause()
        assert int(body.scroll_y) != before
        assert "q close" in footer_text(app)
        assert "^F pane" not in footer_text(app)


async def test_three_pane_footer_shows_focus_both() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await nest_main_top(pilot, app)
        text = footer_text(app)
        assert "^F/^B pane" in text
        assert "q close pane" in text


async def test_third_pane_refuses_with_toast_and_keeps_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str, str]] = []

    def notify(
        _view: Any, message: str, *, severity: str = "information", **_kwargs: Any
    ) -> None:
        notifications.append((message, severity))

    app = SasePager(long_document())
    monkeypatch.setattr(PagerView, "notify", notify)
    async with app.run_test(size=(60, 16)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        grid_before = screen._grid
        await pilot.press("|")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        assert screen._grid == grid_before
        assert ("Not enough room for a third pane.", "information") in notifications


async def test_three_pane_turn_refuses_when_transpose_does_not_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str, str]] = []

    def notify(
        _view: Any, message: str, *, severity: str = "information", **_kwargs: Any
    ) -> None:
        notifications.append((message, severity))

    app = SasePager(long_document())
    monkeypatch.setattr(PagerView, "notify", notify)
    async with app.run_test(size=(100, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await nest_main_top(pilot, app)
        by_id = screen._views_by_id
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert screen.focused_view is by_id[0]
        # Grow the main pane: the outer ratio steps to 70 while the
        # pair still fits, but the transpose would starve the rows.
        await pilot.press("+")
        await pilot.pause()
        assert screen._split_state.ratio == 70
        grid_before = screen._grid
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert screen._grid == grid_before
        assert _geometry(screen._grid) is _Geometry.R3_MAIN_TOP
        assert (
            "Not enough room to turn the panes.",
            "information",
        ) in notifications


async def test_escape_close_keeps_survivor_mounted() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        focused = screen.focused_view
        other = screen.views[0]
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 1
        assert screen.views[0] is other
        assert other.parent is panes_container(app)
        assert mounted_views(app) == [other]
        assert len(other.query("#pager-body-scroll")) == 1
        assert other._body is not None and other._body.total_height > 0
        body = other.query_one("#pager-body-scroll", PagerBodyScroll)
        before = int(body.scroll_y)
        await pilot.press("j")
        await pilot.pause()
        assert int(body.scroll_y) != before
        assert "q close" in footer_text(app)
        assert focused.parent is not panes_container(app)


async def test_exhausted_backspace_close_keeps_survivor_mounted() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        other = screen.views[0]
        await pilot.press("backspace")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 1
        assert screen.views[0] is other
        assert other.parent is panes_container(app)
        assert mounted_views(app) == [other]
        assert len(other.query("#pager-body-scroll")) == 1
        assert other._body is not None and other._body.total_height > 0
        body = other.query_one("#pager-body-scroll", PagerBodyScroll)
        before = int(body.scroll_y)
        await pilot.press("j")
        await pilot.pause()
        assert int(body.scroll_y) != before
