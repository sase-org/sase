"""Tests for the async startup wiring that keeps the stopwatch ticking.

These tests lock in the contract used by
``plans/202604/startup_stopwatch_live_update.md``: ``AceApp.on_mount`` is
a coroutine (so awaits between disk reads yield to the event loop and
``KeybindingFooter._on_stopwatch_tick`` fires), and the new split
helpers are pure disk reads with no Textual widget access.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.changespec import ChangeSpecMixin
from sase.ace.tui.actions.lifecycle import LifecycleMixin
from sase.ace.tui.app import AceApp


def test_on_mount_is_coroutine() -> None:
    """``AceApp.on_mount`` must be async so each disk read can yield."""
    assert inspect.iscoroutinefunction(AceApp.on_mount)


def test_try_startup_fallback_async_is_coroutine() -> None:
    """Fallback path must also be async to keep the event loop free."""
    assert inspect.iscoroutinefunction(ChangeSpecMixin._try_startup_fallback_async)


def test_read_changespecs_from_disk_returns_list() -> None:
    """Pure read helper must return whatever ``find_all_changespecs`` does."""
    mixin = ChangeSpecMixin.__new__(ChangeSpecMixin)
    sentinel = [MagicMock(), MagicMock()]
    with patch(
        "sase.ace.changespec.find_all_changespecs",
        return_value=sentinel,
    ):
        result = mixin._read_changespecs_from_disk()
    assert result is sentinel


def test_read_unread_notification_ids_returns_set() -> None:
    """Pure read helper filters to unread+non-silent and returns ids only."""
    mixin = LifecycleMixin.__new__(LifecycleMixin)
    n_read = MagicMock(id="a", read=True, silent=False)
    n_silent = MagicMock(id="b", read=False, silent=True)
    n_unread = MagicMock(id="c", read=False, silent=False)
    with patch(
        "sase.notifications.load_notifications",
        return_value=[n_read, n_silent, n_unread],
    ):
        result = mixin._read_unread_notification_ids()
    assert result == {"c"}


def test_read_last_selection_name_delegates_to_loader() -> None:
    """Pure read helper forwards whatever ``load_last_selection`` returns."""
    mixin = LifecycleMixin.__new__(LifecycleMixin)
    with patch(
        "sase.ace.last_selection.load_last_selection",
        return_value="foo",
    ):
        assert mixin._read_last_selection_name() == "foo"
    with patch(
        "sase.ace.last_selection.load_last_selection",
        return_value=None,
    ):
        assert mixin._read_last_selection_name() is None
