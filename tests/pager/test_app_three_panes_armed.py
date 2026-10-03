"""Other-pane arming and landing tests for three-pane ``SasePager``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.util.pane_grid import position_glyph, position_name
from sase.pager.app import SasePager
from sase.pager.resolve import LinkTarget, LinkTargetKind
from sase.pager.view import PagerView

from ._app_helpers import (
    link_document,
    long_document,
    pager_screen,
    path_link_document,
    target_document,
)
from ._three_panes_helpers import footer_text, nest_main_top


def _document_resolver(target: Any) -> Any:
    def resolve(ref: str, **_kwargs: Any) -> LinkTarget:
        return LinkTarget(kind=LinkTargetKind.DOCUMENT, document=target)

    return resolve


async def test_ctrl_w_arms_mru_target_with_preview_and_footer() -> None:
    app = SasePager(long_document())
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await nest_main_top(pilot, app)
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
        assert f"^W… other pane {expected}" in footer_text(app)
        # Doubled ctrl+w focuses the captured pane and clears.
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert screen.focused_view is screen._views_by_id[1]
        assert screen.focused_view._pending_action == "follow"
        assert screen._armed_other_target is None
        assert screen._views_by_id[1]._pane_preview is False


async def test_escape_clears_armed_preview() -> None:
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
    app = SasePager(path_link_document(Path("/tmp/target.py")))
    monkeypatch.setattr(PagerView, "notify", notify)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        source_document = screen.focused_view.document
        await nest_main_top(pilot, app)
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


async def test_two_pane_vanished_target_cancels_instead_of_splitting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = target_document()
    notifications: list[tuple[str, str]] = []

    def notify(
        _view: Any, message: str, *, severity: str = "information", **_kwargs: Any
    ) -> None:
        notifications.append((message, severity))

    monkeypatch.setattr("sase.pager.screen.resolve_ref", _document_resolver(target))
    app = SasePager(path_link_document(Path("/tmp/target.py")))
    monkeypatch.setattr(PagerView, "notify", notify)
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        source_document = screen.focused_view.document
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        await pilot.press("ctrl+w")
        await pilot.pause()
        slot = screen._armed_other_target
        assert slot is not None
        captured_id, captured = slot
        # Simulate a label pressed before the close: the pending arm is
        # consumed into an in-flight resolve, so the close must not disarm
        # the capture the landing needs to cancel.
        screen.focused_view._pending_action = "follow"
        screen.close_view(captured)
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 1
        assert captured_id not in screen._grid.panes
        source = screen.focused_view
        screen.show_in_other_view(source, target, None)
        await pilot.pause()
        assert len(screen.views) == 1
        assert (
            "The other pane closed before the link landed.",
            "information",
        ) in notifications
        assert all(view.document is not target for view in screen.views)
        assert screen.focused_view.document is source_document
        assert screen._armed_other_target is None


async def test_armed_url_label_clears_preview_and_capture() -> None:
    app = SasePager(link_document(2))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        await pilot.press("ctrl+w")
        await pilot.pause()
        slot = screen._armed_other_target
        assert slot is not None
        target_id = slot[0]
        assert screen._views_by_id[target_id]._pane_preview is True
        await pilot.press("1")
        await pilot.pause(0.2)
        await pilot.pause(0.2)
        await pilot.pause()
        assert screen._armed_other_target is None
        assert screen._views_by_id[target_id]._pane_preview is False
        assert len(screen.views) == 2


async def test_armed_unresolvable_label_clears_preview_and_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.pager.screen.resolve_ref", lambda ref, **_kwargs: None)
    app = SasePager(path_link_document(Path("/tmp/target.py")))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        await pilot.press("\\")
        await pilot.pause()
        await pilot.pause()
        assert len(screen.views) == 2
        await pilot.press("ctrl+w")
        await pilot.pause()
        slot = screen._armed_other_target
        assert slot is not None
        target_id = slot[0]
        assert screen._views_by_id[target_id]._pane_preview is True
        await pilot.press("0")
        await pilot.pause(0.3)
        await pilot.pause(0.3)
        await pilot.pause()
        assert screen._armed_other_target is None
        assert screen._views_by_id[target_id]._pane_preview is False
        assert len(screen.views) == 2


async def test_structure_change_cancels_arm_and_next_label_follows_in_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = target_document()
    monkeypatch.setattr("sase.pager.screen.resolve_ref", _document_resolver(target))
    app = SasePager(path_link_document(Path("/tmp/target.py")))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = pager_screen(app)
        await pilot.pause()
        source_document = screen.focused_view.document
        await nest_main_top(pilot, app)
        assert len(screen.views) == 3
        await pilot.press("ctrl+w")
        await pilot.pause()
        assert screen._armed_other_target is not None
        assert "^W" in footer_text(app)
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert screen._armed_other_target is None
        assert "^W" not in footer_text(app)
        assert screen.focused_view._pending_action == "follow"
        focused = screen.focused_view
        await pilot.press("0")
        await pilot.pause(0.3)
        await pilot.pause(0.3)
        await pilot.pause()
        assert focused.document is target
        assert screen.focused_view is focused
        assert source_document is not target
