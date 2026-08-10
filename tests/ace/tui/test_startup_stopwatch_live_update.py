"""Tests for startup wiring that keeps first paint and input responsive.

These tests lock in the contract used by
``sdd/plans/202604/startup_stopwatch_live_update.md``: ``AceApp.on_mount``
finishes synchronously, post-mount workers perform disk reads after first
paint, and the split helpers are pure disk reads with no Textual widget access.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.tui.actions.axe_display._data import AxeCollectedData
from sase.ace.tui.actions.patch import PatchMixin
from sase.ace.tui.actions.lifecycle import LifecycleMixin
from sase.ace.tui.modals.notification_modal_tags import NotificationTagTab
from sase.ace.tui.app import AceApp
from sase.ace.testing import AcePage

from tests._notification_toasts_helpers import _FakeApp, _make, _patch_snapshot


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


def test_startup_seeded_activity_generation_does_not_toast_after_startup() -> None:
    app = _FakeApp()
    existing = _make(
        id="existing-startup",
        action="JumpToAgent",
        notes=["already active"],
        timestamp="2026-08-01T09:00:00-04:00",
    )

    with _patch_snapshot([existing]) as startup_read:
        app._initialize_agent_tracking(app._read_notifications_for_startup())

    startup_read.assert_called_once()
    assert app._last_unread_ids == {existing.id}
    assert app._delivered_notification_activity_cursors == {
        ("2026-08-01T09:00:00-04:00", existing.id)
    }

    with _patch_snapshot([existing]):
        saw_new = asyncio.run(app._poll_agent_completions())

    assert saw_new is False
    assert app.notify.call_count == 0
    assert app._bell_rung == 0


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


def test_start_post_mount_background_loads_schedules_all_once() -> None:
    """Startup launcher schedules fold, agent, and axe paths independently."""
    app = AceApp()
    scheduled: list[object] = []
    intervals: list[tuple[float, object, str | None]] = []

    with (
        patch.object(
            app,
            "run_worker",
            side_effect=lambda fn, **kwargs: scheduled.append(fn),
        ),
        patch.object(
            app,
            "set_interval",
            side_effect=lambda seconds, callback, **kwargs: (
                intervals.append((seconds, callback, kwargs.get("name"))) or MagicMock()
            ),
        ),
    ):
        app._start_post_mount_background_loads()
        app._start_post_mount_background_loads()

    assert scheduled.count(app._run_agent_index_startup_prepare_and_refresh) == 1
    assert scheduled.count(app._run_axe_startup_init) == 1
    assert scheduled.count(app._run_mount_state_loads) == 1
    assert scheduled.count(app._run_agents_fold_state_load) == 1
    assert scheduled.count(app._run_startup_update_toast_check) == 1
    assert (
        sum(
            getattr(callback, "func", None) == app._run_agents_sync_status_check
            for callback in scheduled
        )
        == 1
    )
    assert intervals == [
        (600.0, app._on_periodic_update_check, "automatic-update-check"),
        (600.0, app._on_periodic_agents_sync_check, "agents-sync-check"),
    ]
    assert app._post_mount_background_loads_started is True


@pytest.mark.asyncio
async def test_slow_mount_state_read_does_not_block_app_key_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first slow post-mount read must not occupy the App message pump."""
    started = Event()
    release = Event()

    def slow_notifications(
        _self: AceApp,
    ) -> tuple[set[str], set[tuple[str, str]], list[NotificationTagTab]]:
        started.set()
        release.wait()
        return set(), set(), []

    monkeypatch.setattr(AceApp, "_read_notifications_for_startup", slow_notifications)

    async with AcePage(
        wait_for_startup_state=False,
        startup_policy="real",
    ) as page:
        try:
            assert await asyncio.wait_for(
                asyncio.to_thread(started.wait, 10.0), timeout=11.0
            )
            assert page.app.current_tab == "artifacts"
            await page.press("tab")
            await page.wait_for(
                lambda _state: page.app.current_tab != "artifacts",
            )
            assert page.app.current_tab == "axe"
        finally:
            release.set()
            await page.wait_for(
                lambda _state: page.app._mount_state_loads_done,
                timeout=15.0,
            )


def test_startup_configures_periodic_update_interval_from_loaded_config() -> None:
    with patch(
        "sase.config.load_merged_config",
        return_value={"ace": {"updates": {"check_interval_minutes": 1.5}}},
    ):
        app = AceApp()
    intervals: list[tuple[float, object, str | None]] = []

    with patch.object(
        app,
        "set_interval",
        side_effect=lambda seconds, callback, **kwargs: (
            intervals.append((seconds, callback, kwargs.get("name"))) or MagicMock()
        ),
    ):
        app._start_periodic_update_checks()

    assert app._automatic_update_check_interval_seconds == 90.0
    assert intervals == [
        (90.0, app._on_periodic_update_check, "automatic-update-check")
    ]


def test_startup_configures_agents_sync_cadences_from_loaded_config() -> None:
    with patch(
        "sase.config.load_merged_config",
        return_value={
            "ace": {
                "agents_sync": {
                    "check_interval_minutes": 2,
                    "recompute_interval_minutes": 7,
                    "indicator": False,
                }
            }
        },
    ):
        app = AceApp()

    assert app._agents_sync_check_interval_seconds == 120.0
    assert app._agents_sync_recompute_interval_seconds == 420.0
    assert app._agents_sync_indicator_enabled is False


@pytest.mark.asyncio
async def test_start_post_mount_background_loads_does_not_gate_axe_on_agents() -> None:
    """Axe startup should complete even while agents startup is still running."""

    class _Harness:
        def __init__(self) -> None:
            self._post_mount_background_loads_started = False
            self._agents_refresh_pending_callbacks: list[Callable[[], None]] = []
            self.agent_started = asyncio.Event()
            self.agent_release = asyncio.Event()
            self.agent_done = asyncio.Event()
            self.axe_done = asyncio.Event()
            self.fold_started = asyncio.Event()
            self.fold_release = asyncio.Event()
            self.fold_done = asyncio.Event()
            self.tasks: list[asyncio.Task[None]] = []

        async def _run_agent_index_startup_prepare_and_refresh(self) -> None:
            await self._run_agents_async_refresh()

        async def _run_agents_async_refresh(self) -> None:
            self.agent_started.set()
            await self.agent_release.wait()
            self.agent_done.set()

        async def _run_axe_startup_init(self) -> None:
            self.axe_done.set()

        async def _run_agents_fold_state_load(self) -> None:
            self.fold_started.set()
            await self.fold_release.wait()
            self.fold_done.set()

        def _schedule_agents_fold_state_load(self) -> None:
            self.run_worker(self._run_agents_fold_state_load)

        def _schedule_dismissed_index_startup_sync(self) -> None:
            pass

        def _start_artifact_watcher(self) -> None:
            pass

        def run_worker(self, fn, **kwargs) -> None:  # type: ignore[no-untyped-def]
            del kwargs
            self.tasks.append(asyncio.create_task(fn()))

    harness = _Harness()
    AceApp._start_post_mount_background_loads(harness)  # type: ignore[arg-type]

    await asyncio.wait_for(harness.agent_started.wait(), timeout=0.2)
    await asyncio.wait_for(harness.axe_done.wait(), timeout=0.2)
    await asyncio.wait_for(harness.fold_started.wait(), timeout=0.2)
    assert not harness.agent_done.is_set()
    assert not harness.fold_done.is_set()

    harness.agent_release.set()
    harness.fold_release.set()
    await asyncio.wait_for(asyncio.gather(*harness.tasks), timeout=0.2)


def test_maybe_end_startup_stopwatch_requires_both_first_load_flags() -> None:
    """Coordinator should end stopwatch only after both startup loads finish."""
    app = AceApp()
    footer = MagicMock()

    with patch.object(app, "query_one", return_value=footer):
        app._agents_first_load_done = True
        app._axe_first_load_done = False
        app._maybe_end_startup_stopwatch()

        app._agents_first_load_done = False
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()

        app._agents_first_load_done = True
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()

    footer.end_startup_stopwatch.assert_called_once()


def test_maybe_end_startup_stopwatch_is_safe_when_called_repeatedly() -> None:
    """Repeated coordinator calls rely on footer idempotency and stay safe."""

    class _Footer:
        def __init__(self) -> None:
            self.active = True
            self.end_calls = 0

        def end_startup_stopwatch(self) -> None:
            if not self.active:
                return
            self.active = False
            self.end_calls += 1

    app = AceApp()
    footer = _Footer()

    with patch.object(app, "query_one", return_value=footer):
        app._agents_first_load_done = True
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()
        app._maybe_end_startup_stopwatch()

    assert footer.end_calls == 1


def test_axe_first_load_path_no_longer_ends_stopwatch_directly() -> None:
    """AXE first-load applies must route through the coordinator (not direct end)."""
    app = AceApp()
    app._agents_first_load_done = False
    app._axe_first_load_done = False
    footer = MagicMock()

    def _query_one(selector: str, *_args: object, **_kwargs: object) -> object:
        if selector == "#axe-dashboard":
            return MagicMock()
        if selector == "#axe-info-panel":
            panel = MagicMock()
            panel.set_loading = MagicMock()
            return panel
        if selector == "#keybinding-footer":
            return footer
        return MagicMock()

    data = AxeCollectedData(
        axe_running=False,
        axe_status=None,
        axe_metrics=None,
        axe_output="",
        lumberjack_names=[],
        bgcmd_slots=[],
        lumberjack_statuses={},
        lumberjack_metrics={},
        lumberjack_log_tails={},
        bgcmd_details={},
        lumberjack_chop_names={},
        chop_snapshots={},
        lumberjack_snapshots={},
    )

    with (
        patch.object(app, "query_one", side_effect=_query_one),
        patch.object(app, "_update_bgcmd_count", return_value=None),
        patch.object(app, "_build_axe_items", return_value=None),
        patch.object(app, "_update_axe_keybinding", return_value=None),
    ):
        app._apply_axe_status_data(data)

    footer.end_startup_stopwatch.assert_not_called()


def test_stopwatch_ends_when_second_startup_surface_finishes() -> None:
    """Simulate each first-load completion path; second completion ends stopwatch."""

    class _Footer:
        def __init__(self) -> None:
            self.active = True
            self.end_calls = 0

        def end_startup_stopwatch(self) -> None:
            if not self.active:
                return
            self.active = False
            self.end_calls += 1

    app = AceApp()
    footer = _Footer()

    with patch.object(app, "query_one", return_value=footer):
        # Simulate agents first load finishing first.
        app._agents_first_load_done = True
        app._maybe_end_startup_stopwatch()
        assert footer.end_calls == 0

        # Simulate axe first load finishing second.
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()
        assert footer.end_calls == 1
