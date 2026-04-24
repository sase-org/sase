"""Tests for the two-phase startup wiring that keeps the stopwatch ticking.

These tests lock in the contract used by
``plans/202604/startup_stopwatch_batch_update_fix.md``: ``AceApp.on_mount``
is **sync** and only wires the in-batch essentials before scheduling
``_finish_startup`` via ``call_after_refresh``. ``_finish_startup`` is a
coroutine that runs the actual startup I/O outside Textual's mount batch
so the ``KeybindingFooter`` stopwatch ticks can paint. The split disk-read
helpers remain pure functions with no Textual widget access.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.changespec import ChangeSpecMixin
from sase.ace.tui.actions.lifecycle import LifecycleMixin
from sase.ace.tui.app import AceApp


def test_on_mount_is_sync() -> None:
    """``AceApp.on_mount`` must be sync so it returns promptly and lets
    Textual exit its mount ``batch_update`` to paint the first frame."""
    assert not inspect.iscoroutinefunction(AceApp.on_mount)


def test_finish_startup_is_coroutine() -> None:
    """``AceApp._finish_startup`` must be async so each disk read can yield
    outside the mount batch, keeping the stopwatch's paints unblocked."""
    assert inspect.iscoroutinefunction(AceApp._finish_startup)


def test_on_mount_schedules_finish_startup_via_call_after_refresh() -> None:
    """``on_mount`` must defer the heavy work via ``call_after_refresh``
    so it runs after the first paint (i.e. outside the mount batch)."""
    import textwrap

    src = textwrap.dedent(inspect.getsource(AceApp.on_mount))
    assert "call_after_refresh" in src
    assert "_finish_startup" in src


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
