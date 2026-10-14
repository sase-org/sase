"""Contract and pure-read tests for ACE startup."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.lifecycle import LifecycleMixin
from sase.ace.tui.actions.patch import PatchMixin
from sase.ace.tui.app import AceApp
from sase.ace.tui.modals.notification_modal_tags import NotificationTagTab


def test_on_mount_is_synchronous() -> None:
    """``AceApp.on_mount`` must return before any slow disk body runs."""
    assert not inspect.iscoroutinefunction(AceApp.on_mount)
    assert "to_thread" not in inspect.getsource(AceApp.on_mount)


def test_on_mount_seeds_current_tab_in_trace_context() -> None:
    """``on_mount`` seeds the trace context with ``current_tab`` up front.

    Without this seed, startup-phase spans (notifications read,
    patches read, the first agents/axe loads) all emit
    ``current_tab=None`` because ``watch_current_tab`` only fires on
    later transitions.
    """
    src = inspect.getsource(AceApp.on_mount)
    assert "set_trace_context(current_tab=self.current_tab)" in src
    # Must be inside the ``self._mounting = True`` block, before the
    # first widget access, so the seed precedes any span emission.
    mounting_idx = src.index("self._mounting = True")
    seed_idx = src.index("set_trace_context(current_tab=self.current_tab)")
    first_query_idx = src.index("self.query_one")
    assert mounting_idx < seed_idx < first_query_idx


def test_first_paint_marker_precedes_non_frame_startup_services() -> None:
    """Non-visible services must wait until after the first frame is marked."""
    mount_src = inspect.getsource(AceApp.on_mount)
    assert "_schedule_link_index_refresh" not in mount_src
    assert "_start_proc_reconciler" not in mount_src
    assert "start_event_loop_stall_watchdog" not in mount_src
    assert "start_tui_heap_sampler" not in mount_src
    assert '"auto-refresh"' not in mount_src

    launcher_src = inspect.getsource(AceApp._start_post_mount_background_loads)
    first_paint_idx = launcher_src.index("self._mark_startup_first_paint()")
    services_idx = launcher_src.index("self._start_post_first_paint_services()")
    fallback_idx = launcher_src.index("self._arm_startup_deferred_fallback()")
    immediate_idx = launcher_src.index("self._start_immediate_startup_loads()")
    assert first_paint_idx < services_idx < fallback_idx < immediate_idx


def test_read_patches_from_disk_returns_list() -> None:
    """Pure read helper must return whatever the cached loader does."""
    mixin = PatchMixin.__new__(PatchMixin)
    sentinel = [MagicMock(), MagicMock()]
    with patch(
        "sase.ace.patch.find_all_patches_cached",
        return_value=sentinel,
    ):
        result = mixin._read_patches_from_disk()
    assert result is sentinel


def test_read_unread_notification_ids_returns_set() -> None:
    """Pure read helper filters to unread+non-silent+non-muted and returns ids only."""
    mixin = LifecycleMixin.__new__(LifecycleMixin)
    n_read = MagicMock(id="a", read=True, silent=False, muted=False)
    n_silent = MagicMock(id="b", read=False, silent=True, muted=False)
    n_muted = MagicMock(id="d", read=False, silent=False, muted=True)
    n_unread = MagicMock(id="c", read=False, silent=False, muted=False)
    with patch(
        "sase.notifications.read_notification_snapshot",
        return_value=SimpleNamespace(
            notifications=[n_read, n_silent, n_muted, n_unread]
        ),
    ):
        result = mixin._read_unread_notification_ids()
    assert result == {"c"}


def test_read_notifications_for_startup_uses_snapshot_tabs() -> None:
    """Startup indicator chips come from the Rust-backed snapshot tabs."""
    mixin = LifecycleMixin.__new__(LifecycleMixin)
    timestamp = "2026-08-01T09:00:00-04:00"
    n_priority = MagicMock(
        id="a",
        read=False,
        silent=False,
        muted=False,
        timestamp=timestamp,
        resurfaced_at=None,
    )
    n_muted = MagicMock(
        id="b",
        read=False,
        silent=False,
        muted=True,
        timestamp="2026-08-01T09:01:00-04:00",
        resurfaced_at=None,
    )
    snapshot = SimpleNamespace(
        notifications=[n_priority, n_muted],
        counts=SimpleNamespace(priority=7, errors=4, rest=3, muted=2),
        tabs=[
            SimpleNamespace(
                key="hitl",
                kind="hitl",
                count=7,
                oldest_activity_at=timestamp,
                next_wake_at=None,
                color=None,
            ),
            SimpleNamespace(
                key="__muted__",
                kind="muted",
                count=2,
                oldest_activity_at=None,
                next_wake_at=None,
                color=None,
            ),
        ],
    )
    with patch("sase.notifications.read_notification_snapshot", return_value=snapshot):
        assert mixin._read_notifications_for_startup() == (
            {"a"},
            {(timestamp, "a")},
            [
                NotificationTagTab(
                    tag="hitl",
                    label="Gates",
                    count=7,
                    kind="hitl",
                    oldest_activity_at=timestamp,
                ),
                NotificationTagTab(
                    tag="__muted__",
                    label="Muted",
                    count=2,
                    kind="muted",
                ),
            ],
        )


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
