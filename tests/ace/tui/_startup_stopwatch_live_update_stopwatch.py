"""Startup stopwatch coordination tests."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.axe_display._data import AxeCollectedData
from sase.ace.tui.app import AceApp


def test_maybe_end_startup_stopwatch_gates_on_visible_tab_only() -> None:
    """Coordinator ends the stopwatch once the initially visible tab is ready.

    The hidden tab's own load state must not matter — that is the point of
    the visible-surface gate: a future hidden-tab feature cannot regress
    every startup mode just by taking longer to finish loading.
    """
    app = AceApp()
    footer = MagicMock()

    with patch.object(app, "query_one", return_value=footer):
        app._startup_initial_tab = "agents"
        app._agents_first_load_done = False
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()
        footer.end_startup_stopwatch.assert_not_called()

        app._agents_first_load_done = True
        app._maybe_end_startup_stopwatch()

    footer.end_startup_stopwatch.assert_called_once()


def test_maybe_end_startup_stopwatch_clears_startup_window_flag() -> None:
    """Visible-ready ends the tagged startup window so later spans omit it."""
    from sase.ace.tui.util import trace

    app = AceApp()
    footer = MagicMock()
    trace.set_startup_window(True)
    with patch.object(app, "query_one", return_value=footer):
        app._startup_initial_tab = "agents"
        app._agents_first_load_done = True
        app._maybe_end_startup_stopwatch()
    assert trace._startup_window is False
    footer.end_startup_stopwatch.assert_called_once()


def test_maybe_end_startup_stopwatch_gates_on_axe_when_axe_is_visible() -> None:
    """When axe is the initially visible tab, only its readiness gates."""
    app = AceApp()
    footer = MagicMock()

    with patch.object(app, "query_one", return_value=footer):
        app._startup_initial_tab = "services"
        app._agents_first_load_done = False
        app._axe_first_load_done = False
        app._maybe_end_startup_stopwatch()
        footer.end_startup_stopwatch.assert_not_called()

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
        app._startup_initial_tab = "agents"
        app._agents_first_load_done = True
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()
        app._maybe_end_startup_stopwatch()

    assert footer.end_calls == 1


def test_axe_first_load_path_no_longer_ends_stopwatch_directly() -> None:
    """AXE first-load applies must route through the coordinator (not direct end)."""
    app = AceApp()
    app._startup_initial_tab = "agents"
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


def test_stopwatch_ends_as_soon_as_visible_surface_finishes_first() -> None:
    """The hidden surface finishing later must not be required to end it."""

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
    app._startup_initial_tab = "agents"
    footer = _Footer()

    with patch.object(app, "query_one", return_value=footer):
        # The hidden (axe) surface finishing first must not end it early.
        app._axe_first_load_done = True
        app._maybe_end_startup_stopwatch()
        assert footer.end_calls == 0

        # The visible (agents) surface finishing ends it immediately.
        app._agents_first_load_done = True
        app._maybe_end_startup_stopwatch()
        assert footer.end_calls == 1


def test_old_three_second_mark_does_not_release_deferred_loads() -> None:
    """The 45 s safety timer is the only fallback; 3 s no longer releases."""
    app = AceApp()
    app._mark_startup_on_mount()
    delays: list[float] = []

    def capture_timer(
        seconds: float,
        callback: Callable[[], None],
        **kwargs: object,
    ) -> MagicMock:
        del callback, kwargs
        delays.append(seconds)
        return MagicMock()

    with (
        patch.object(app, "run_worker"),
        patch.object(app, "_start_post_first_paint_services"),
        patch.object(app, "set_timer", side_effect=capture_timer),
        patch.object(app, "set_interval", return_value=MagicMock()),
        patch.object(app, "_start_artifact_watcher"),
        patch.object(app, "_start_prompt_source_watcher"),
    ):
        app._start_post_mount_background_loads()

    assert delays == [45.0]
    assert app._startup_deferred_loads_released is False
    assert app._startup_visible_ready_mono is None
