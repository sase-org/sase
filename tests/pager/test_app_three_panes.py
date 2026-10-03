"""Headless Pilot three-pane tests for ``SasePager``.

Covers the ``three_pane_splits`` beta flag on the pager: nesting into all
four T shapes, erase and turn, closing each of the three panes, MRU
``ctrl+w`` with its preview frame and footer, fit refusal, and the
flag-off rotate behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from textual.containers import Vertical
from textual.widgets import Static

from sase.ace.tui.util.pane_grid import (
    Geometry,
    geometry,
    grid_spec,
    position_glyph,
    position_name,
)
from sase.feature_flags import override_flags
from sase.pager.app import SasePager
from sase.pager.resolve import LinkTarget, LinkTargetKind
from sase.pager.split import PagerSplitLayout
from sase.pager.view import PagerView

from ._app_helpers import (
    long_document,
    pager_screen,
    path_link_document,
    target_document,
)


def _footer_text(app: SasePager) -> str:
    footer = pager_screen(app).query_one("#pager-footer", Static)
    visual = getattr(footer, "visual", None)
    if visual is not None:
        return str(visual.plain)
    content = getattr(footer, "_content", "")
    return str(getattr(content, "plain", content))


def _panes_container(app: SasePager) -> Vertical:
    return pager_screen(app).query_one("#pager-panes", Vertical)


def _mounted_views(app: SasePager) -> list[PagerView]:
    return list(pager_screen(app).query(PagerView))


def _document_resolver(target: Any) -> Any:
    def resolve(ref: str, **_kwargs: Any) -> LinkTarget:
        return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target)

    return resolve


async def _nest_main_top(pilot: Any, app: SasePager) -> Any:
    """Drive ``\\`` then ``|`` to an R3 main-top grid; return the screen."""
    screen = pager_screen(app)
    await pilot.press("\\")
    await pilot.pause()
    await pilot.pause()
    assert len(screen.views) == 2
    await pilot.press("|")
    await pilot.pause()
    await pilot.pause()
    assert len(screen.views) == 3
    assert geometry(screen._grid) is Geometry.R3_MAIN_TOP
    return screen


async def test_nest_reaches_all_four_t_shapes() -> None:
    with override_flags(three_pane_splits=True):
        app = SasePager(long_document())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = pager_screen(app)
            await pilot.pause()
            # Main-top: split below, then nest the focused bottom pane.
            await _nest_main_top(pilot, app)
            assert screen._grid.focused == 2
            # Collapse back to single through the pair, keeping focus.
            # Erasing R3 along its outer axis leaves the C2 pair, and the
            # same-axis key then keeps the focused pane.
            await pilot.press("\\")
            await pilot.pause()
            await pilot.pause()
            assert len(screen.views) == 2
            assert geometry(screen._grid) is Geometry.C2
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
            assert geometry(screen._grid) is Geometry.R3_MAIN_BOTTOM
            # Collapse again: erase to the C2 pair, then unsplit.
            await pilot.press("\\")
            await pilot.pause()
            await pilot.pause()
            assert len(screen.views) == 2
            assert geometry(screen._grid) is Geometry.C2
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
            assert geometry(screen._grid) is Geometry.C3_MAIN_LEFT
            # Collapse: erase to the R2 pair, then unsplit.
            await pilot.press("|")
            await pilot.pause()
            await pilot.pause()
            assert len(screen.views) == 2
            assert geometry(screen._grid) is Geometry.R2
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
            assert geometry(screen._grid) is Geometry.C3_MAIN_RIGHT


async def test_nest_keeps_survivor_widgets_and_focuses_new_pane() -> None:
    with override_flags(three_pane_splits=True):
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
            assert geometry(screen._grid) is Geometry.R3_MAIN_TOP
            by_id = screen._views_by_id
            assert by_id[0] is first
            assert by_id[1] is second
            # No survivor remounted: all three are children in DOM order.
            dom_order = grid_spec(screen._grid).dom_order
            assert [
                c for c in _panes_container(app).children if c in by_id.values()
            ] == [by_id[pane_id] for pane_id in dom_order]
            assert set(_mounted_views(app)) == set(screen.views)
            # The new pane takes focus; the unfocused pane is now main.
            assert screen.focused_view is by_id[2]
            assert screen._split_state.layout is PagerSplitLayout.BELOW


async def test_erase_with_main_focused_collapses_to_single() -> None:
    with override_flags(three_pane_splits=True):
        app = SasePager(long_document())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = pager_screen(app)
            await pilot.pause()
            await _nest_main_top(pilot, app)
            main = screen._views_by_id[0]
            await pilot.press("ctrl+f")
            await pilot.pause()
            assert screen.focused_view is main
            await pilot.press("\\")
            await pilot.pause()
            await pilot.pause()
            assert len(screen.views) == 1
            assert screen.views[0] is main
            assert main.parent is _panes_container(app)
            assert _mounted_views(app) == [main]
            assert screen._split_state.layout is PagerSplitLayout.SINGLE


async def test_erase_with_pair_focused_keeps_the_pair() -> None:
    with override_flags(three_pane_splits=True):
        app = SasePager(long_document())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = pager_screen(app)
            await pilot.pause()
            await _nest_main_top(pilot, app)
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
            assert _mounted_views(app) == [pair_first, pair_second]


async def test_split_keys_turn_three_panes_both_ways() -> None:
    with override_flags(three_pane_splits=True):
        app = SasePager(long_document())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = pager_screen(app)
            await pilot.pause()
            await _nest_main_top(pilot, app)
            before = list(screen.views)
            await pilot.press("|")
            await pilot.pause()
            assert geometry(screen._grid) is Geometry.C3_MAIN_LEFT
            assert list(screen.views) == before
            assert _mounted_views(app) == before
            await pilot.press("\\")
            await pilot.pause()
            assert geometry(screen._grid) is Geometry.R3_MAIN_TOP
            assert list(screen.views) == before
            assert _mounted_views(app) == before


async def test_ctrl_t_turns_three_panes_keeping_widgets() -> None:
    with override_flags(three_pane_splits=True):
        app = SasePager(long_document())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = pager_screen(app)
            await pilot.pause()
            await _nest_main_top(pilot, app)
            before = list(screen.views)
            focused = screen.focused_view
            await pilot.press("ctrl+t")
            await pilot.pause()
            assert geometry(screen._grid) is Geometry.C3_MAIN_LEFT
            assert list(screen.views) == before
            assert screen.focused_view is focused
            await pilot.press("ctrl+t")
            await pilot.pause()
            assert geometry(screen._grid) is Geometry.R3_MAIN_TOP
            assert list(screen.views) == before
            assert _mounted_views(app) == before


async def test_close_pair_pane_keeps_outer_split_and_mru_focus() -> None:
    with override_flags(three_pane_splits=True):
        app = SasePager(long_document())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = pager_screen(app)
            await pilot.pause()
            await _nest_main_top(pilot, app)
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
            assert screen._views_by_id[1].parent is _panes_container(app)
            assert _mounted_views(app) == list(screen.views)
            assert len(screen.focused_view.query("#pager-body")) == 1


async def test_close_main_pane_leaves_the_pair() -> None:
    with override_flags(three_pane_splits=True):
        app = SasePager(long_document())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = pager_screen(app)
            await pilot.pause()
            await _nest_main_top(pilot, app)
            main = screen._views_by_id[0]
            await pilot.press("ctrl+f")
            await pilot.pause()
            assert screen.focused_view is main
            await pilot.press("q")
            await pilot.pause()
            await pilot.pause()
            assert len(screen.views) == 2
            assert main not in screen.views
            assert geometry(screen._grid) is Geometry.C2
            # MRU order was (0, 2, 1): the survivor focus is pane 2.
            assert screen.focused_view is screen._views_by_id[2]
            assert _mounted_views(app) == list(screen.views)
            assert len(screen.focused_view.query("#pager-body")) == 1


async def test_close_last_of_three_keeps_mounted_scrolling_survivor() -> None:
    with override_flags(three_pane_splits=True):
        app = SasePager(long_document())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = pager_screen(app)
            await pilot.pause()
            await _nest_main_top(pilot, app)
            await pilot.press("q")
            await pilot.pause()
            await pilot.pause()
            assert len(screen.views) == 2
            assert _mounted_views(app) == list(screen.views)
            await pilot.press("q")
            await pilot.pause()
            await pilot.pause()
            assert len(screen.views) == 1
            survivor = screen.views[0]
            assert survivor.parent is _panes_container(app)
            assert _mounted_views(app) == [survivor]
            assert len(survivor.query("#pager-body")) == 1
            assert screen._split_state.layout is PagerSplitLayout.SINGLE
            await pilot.press("j")
            await pilot.pause()
            assert "q close" in _footer_text(app)
            assert "^F pane" not in _footer_text(app)


async def test_swap_in_three_panes_keeps_identity_then_click_focuses() -> None:
    with override_flags(three_pane_splits=True):
        app = SasePager(long_document())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = pager_screen(app)
            await pilot.pause()
            await _nest_main_top(pilot, app)
            by_id = screen._views_by_id
            focused = screen.focused_view
            assert focused is by_id[2]
            await pilot.press("greater_than_sign")
            await pilot.pause()
            # Reading order was (0, 1, 2): pane 2 swaps with pane 0.
            assert screen._grid.panes == (2, 1, 0)
            assert screen.focused_view is focused
            assert set(by_id.values()) == set(screen.views)
            assert _mounted_views(app) == list(screen.views)
            by_id[1].on_click(object())
            await pilot.pause()
            assert screen.focused_view is by_id[1]


async def test_three_pane_footer_shows_focus_both() -> None:
    with override_flags(three_pane_splits=True):
        app = SasePager(long_document())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _nest_main_top(pilot, app)
            text = _footer_text(app)
            assert "^F/^B pane" in text
            assert "q close pane" in text


async def test_ctrl_w_arms_mru_target_with_preview_and_footer() -> None:
    with override_flags(three_pane_splits=True):
        app = SasePager(long_document())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = pager_screen(app)
            await pilot.pause()
            await _nest_main_top(pilot, app)
            # MRU order is (2, 1, 0): the other target from pane 2 is 1.
            await pilot.press("ctrl+w")
            await pilot.pause()
            assert screen.focused_view._pending_action == "other"
            slot = screen._armed_other_target
            assert slot is not None
            assert slot[0] == 1
            assert slot[1] is screen._views_by_id[1]
            assert screen._views_by_id[1]._pane_preview is True
            assert screen._views_by_id[2]._pane_preview is False
            assert screen._views_by_id[0]._pane_preview is False
            grid = screen._grid
            expected = f"{position_glyph(grid, 1)} {position_name(grid, 1)}"
            assert f"^W… other pane {expected}" in _footer_text(app)
            # Doubled ctrl+w focuses the captured pane and clears.
            await pilot.press("ctrl+w")
            await pilot.pause()
            assert screen.focused_view is screen._views_by_id[1]
            assert screen.focused_view._pending_action == "follow"
            assert screen._armed_other_target is None
            assert screen._views_by_id[1]._pane_preview is False


async def test_escape_clears_armed_preview() -> None:
    with override_flags(three_pane_splits=True):
        app = SasePager(path_link_document(Path("/tmp/target.py")))
        async with app.run_test(size=(120, 40)) as pilot:
            screen = pager_screen(app)
            await pilot.pause()
            await pilot.press("\\")
            await pilot.pause()
            await pilot.pause()
            await pilot.press("ctrl+w")
            await pilot.pause()
            assert screen._armed_other_target is not None
            target_id = screen._armed_other_target[0]
            assert screen._views_by_id[target_id]._pane_preview is True
            await pilot.press("escape")
            await pilot.pause()
            assert screen.focused_view._pending_action == "follow"
            assert screen._armed_other_target is None
            assert screen._views_by_id[target_id]._pane_preview is False
            assert len(screen.views) == 2


async def test_ctrl_w_label_lands_in_captured_pane_with_own_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = target_document()
    monkeypatch.setattr("sase.pager.screen.resolve_ref", _document_resolver(target))
    with override_flags(three_pane_splits=True):
        app = SasePager(path_link_document(Path("/tmp/target.py")))
        async with app.run_test(size=(120, 40)) as pilot:
            screen = pager_screen(app)
            await pilot.pause()
            source_document = screen.focused_view.document
            await pilot.press("\\")
            await pilot.pause()
            await pilot.pause()
            await pilot.press("|")
            await pilot.pause()
            await pilot.pause()
            assert len(screen.views) == 3
            source = screen.focused_view
            assert source.document is source_document
            await pilot.press("ctrl+w")
            await pilot.pause()
            slot = screen._armed_other_target
            assert slot is not None
            captured = slot[1]
            await pilot.press("0")
            await pilot.pause(0.3)
            await pilot.pause(0.3)
            await pilot.pause()
            assert screen.focused_view is source
            assert source.document is source_document
            assert captured.document is target
            assert captured._back_trail
            assert captured._back_trail[-1].document is source_document
            # History moved only in the destination.
            assert not source._back_trail
            assert screen._armed_other_target is None
            assert captured._pane_preview is False


async def test_armed_landing_cancels_when_target_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = target_document()
    notifications: list[tuple[str, str]] = []

    def notify(
        _view: Any, message: str, *, severity: str = "information", **_kwargs: Any
    ) -> None:
        notifications.append((message, severity))

    monkeypatch.setattr("sase.pager.screen.resolve_ref", _document_resolver(target))
    with override_flags(three_pane_splits=True):
        app = SasePager(path_link_document(Path("/tmp/target.py")))
        monkeypatch.setattr(PagerView, "notify", notify)
        async with app.run_test(size=(120, 40)) as pilot:
            screen = pager_screen(app)
            await pilot.pause()
            source_document = screen.focused_view.document
            await _nest_main_top(pilot, app)
            await pilot.press("ctrl+w")
            await pilot.pause()
            slot = screen._armed_other_target
            assert slot is not None
            captured_id, captured = slot
            # Remove the captured pane before the armed label lands: the
            # close focuses its victim first, exactly as the keyboard race
            # between an in-flight resolve and a pane close would.
            screen.close_view(captured)
            await pilot.pause()
            await pilot.pause()
            await pilot.pause()
            assert len(screen.views) == 2
            assert captured_id not in screen._grid.panes
            # The armed landing funnels here once its resolve returns.
            source = screen.focused_view
            screen.show_in_other_view(source, target, None)
            await pilot.pause()
            assert (
                "The other pane closed before the link landed.",
                "information",
            ) in notifications
            # Never redirected: no surviving pane shows the target.
            assert all(view.document is not target for view in screen.views)
            assert screen.focused_view.document is source_document


async def test_third_pane_refuses_with_toast_and_keeps_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str, str]] = []

    def notify(
        _view: Any, message: str, *, severity: str = "information", **_kwargs: Any
    ) -> None:
        notifications.append((message, severity))

    with override_flags(three_pane_splits=True):
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

    with override_flags(three_pane_splits=True):
        app = SasePager(long_document())
        monkeypatch.setattr(PagerView, "notify", notify)
        async with app.run_test(size=(100, 40)) as pilot:
            screen = pager_screen(app)
            await pilot.pause()
            await _nest_main_top(pilot, app)
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
            assert geometry(screen._grid) is Geometry.R3_MAIN_TOP
            assert (
                "Not enough room to turn the panes.",
                "information",
            ) in notifications


async def test_flag_off_keeps_rotate_and_never_nests() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        await pilot.press("|")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        assert screen._split_state.layout is PagerSplitLayout.BESIDE
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        assert screen._split_state.layout is PagerSplitLayout.BELOW
        assert "^F pane" in _footer_text(app)
        assert "^F/^B pane" not in _footer_text(app)


async def test_rapid_structural_keys_leave_a_valid_mounted_layout() -> None:
    with override_flags(three_pane_splits=True):
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
            assert _mounted_views(app) == list(screen.views)
            for view in screen.views:
                assert view.parent is _panes_container(app)


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
        assert other.parent is _panes_container(app)
        assert _mounted_views(app) == [other]
        assert len(other.query("#pager-body")) == 1
        await pilot.press("j")
        await pilot.pause()
        assert "q close" in _footer_text(app)
        assert focused.parent is not _panes_container(app)


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
        assert other.parent is _panes_container(app)
        assert _mounted_views(app) == [other]
        assert len(other.query("#pager-body")) == 1
