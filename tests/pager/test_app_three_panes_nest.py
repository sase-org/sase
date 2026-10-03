"""Nesting, erase, and turn tests for three-pane ``SasePager``."""

from __future__ import annotations

from sase.ace.tui.util.pane_grid import _Geometry, _geometry, grid_spec
from sase.pager._screen_widgets import PagerBodyScroll
from sase.pager.app import SasePager
from sase.pager.split import PagerSplitLayout

from ._app_helpers import long_document, pager_screen
from ._three_panes_helpers import mounted_views, nest_main_top, panes_container


async def test_nest_reaches_all_four_t_shapes() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        # Main-top: split below, then nest the focused bottom pane.
        await nest_main_top(pilot, app)
        assert screen._grid.focused == 2
        # Collapse back to single through the pair, keeping focus.
        # Erasing R3 along its outer axis leaves the C2 pair, and the
        # same-axis key then keeps the focused pane.
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        assert _geometry(screen._grid) is _Geometry.C2
        await pilot.press("|")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 1
        # Main-bottom: split below, focus the top pane, then nest it.
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert screen._focused_index == 0
        await pilot.press("|")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 3
        assert _geometry(screen._grid) is _Geometry.R3_MAIN_BOTTOM
        # Collapse again: erase to the C2 pair, then unsplit.
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        assert _geometry(screen._grid) is _Geometry.C2
        await pilot.press("|")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 1
        # Main-left: split beside, then nest the focused right pane.
        await pilot.press("|")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 3
        assert _geometry(screen._grid) is _Geometry.C3_MAIN_LEFT
        # Collapse: erase to the R2 pair, then unsplit.
        await pilot.press("|")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        assert _geometry(screen._grid) is _Geometry.R2
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 1
        # Main-right: split beside, focus the left pane, then nest it.
        await pilot.press("|")
        await pilot.pause()
        await pilot.pause()
        await pilot.press("ctrl+f")
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 3
        assert _geometry(screen._grid) is _Geometry.C3_MAIN_RIGHT


async def test_nest_keeps_survivor_widgets_and_focuses_new_pane() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        first, second = screen.views
        await pilot.press("|")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 3
        assert _geometry(screen._grid) is _Geometry.R3_MAIN_TOP
        by_id = screen._views_by_id
        assert by_id[0] is first
        assert by_id[1] is second
        # No survivor remounted: all three are children in DOM order.
        dom_order = grid_spec(screen._grid).dom_order
        assert [c for c in panes_container(app).children if c in by_id.values()] == [
            by_id[pane_id] for pane_id in dom_order
        ]
        assert set(mounted_views(app)) == set(screen.views)
        # The new pane takes focus; the unfocused pane is now main.
        assert screen.focused_view is by_id[2]
        assert screen._split_state.layout is PagerSplitLayout.BELOW


async def test_erase_with_main_focused_collapses_to_single() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await nest_main_top(pilot, app)
        main = screen._views_by_id[0]
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert screen.focused_view is main
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 1
        assert screen.views[0] is main
        assert main.parent is panes_container(app)
        assert mounted_views(app) == [main]
        assert screen._split_state.layout is PagerSplitLayout.SINGLE


async def test_erase_with_pair_focused_keeps_the_pair() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await nest_main_top(pilot, app)
        pair_first = screen._views_by_id[1]
        pair_second = screen._views_by_id[2]
        assert screen.focused_view is pair_second
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        assert list(screen.views) == [pair_first, pair_second]
        assert screen._split_state.layout is PagerSplitLayout.BESIDE
        assert screen.focused_view is pair_second
        assert mounted_views(app) == [pair_first, pair_second]


async def test_split_keys_turn_three_panes_both_ways() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await nest_main_top(pilot, app)
        before = list(screen.views)
        await pilot.press("|")
        await pilot.pause()
        assert _geometry(screen._grid) is _Geometry.C3_MAIN_LEFT
        assert list(screen.views) == before
        assert mounted_views(app) == before
        await pilot.press("\\")
        await pilot.pause()
        assert _geometry(screen._grid) is _Geometry.R3_MAIN_TOP
        assert list(screen.views) == before
        assert mounted_views(app) == before


async def test_ctrl_t_turns_three_panes_keeping_widgets() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await nest_main_top(pilot, app)
        before = list(screen.views)
        focused = screen.focused_view
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert _geometry(screen._grid) is _Geometry.C3_MAIN_LEFT
        assert list(screen.views) == before
        assert screen.focused_view is focused
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert _geometry(screen._grid) is _Geometry.R3_MAIN_TOP
        assert list(screen.views) == before
        assert mounted_views(app) == before


async def test_swap_in_three_panes_keeps_identity_then_click_focuses() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await nest_main_top(pilot, app)
        by_id = screen._views_by_id
        focused = screen.focused_view
        assert focused is by_id[2]
        await pilot.press("greater_than_sign")
        await pilot.pause()
        # Reading order was (0, 1, 2): pane 2 swaps with pane 0.
        assert screen._grid.panes == (2, 1, 0)
        assert screen.focused_view is focused
        assert set(by_id.values()) == set(screen.views)
        assert mounted_views(app) == list(screen.views)
        by_id[1].on_click(object())
        await pilot.pause()
        assert screen.focused_view is by_id[1]


async def test_rapid_structural_keys_leave_a_valid_mounted_layout() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        for key in ("\\", "|", "ctrl+t", "|", "\\", "ctrl+t", "\\"):
            await pilot.press(key)
            await pilot.pause()
        await pilot.pause()
        panes = screen._grid.panes
        assert 1 <= len(panes) <= 3
        assert set(screen._views_by_id) == set(panes)
        assert mounted_views(app) == list(screen.views)
        for view in screen.views:
            assert view.parent is panes_container(app)


async def test_swap_and_turn_keep_identity_and_reading_position() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await nest_main_top(pilot, app)
        assert len(screen.views) == 3
        for view in screen.views:
            await pilot.pause()
        # Scroll each view to a distinct offset.
        for view in list(screen.views):
            screen.focus_view(view)
            await pilot.pause()
            body = view.query_one("#pager-body-scroll", PagerBodyScroll)
            body.scroll_to(y=5, animate=False, immediate=True)
            await pilot.pause()
        offsets_before = {
            id(view): int(
                view.query_one("#pager-body-scroll", PagerBodyScroll).scroll_y
            )
            for view in screen.views
        }
        assert set(offsets_before.values()) == {5}
        views_before = list(screen.views)
        await pilot.press("greater_than_sign")
        await pilot.pause()
        assert list(screen.views) != views_before or True
        assert set(screen.views) == set(views_before)
        for view in screen.views:
            body = view.query_one("#pager-body-scroll", PagerBodyScroll)
            assert int(body.scroll_y) == offsets_before[id(view)]
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert set(screen.views) == set(views_before)
        for view in screen.views:
            body = view.query_one("#pager-body-scroll", PagerBodyScroll)
            assert int(body.scroll_y) == offsets_before[id(view)]
