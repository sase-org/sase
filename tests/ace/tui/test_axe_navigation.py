"""Axe-tab navigation must not hit disk.

Before this change, Ctrl+N / Ctrl+P on the Axe tab re-read every
lumberjack's status, metrics, and log tail from disk on each keypress.
With many lumberjacks configured this stalled the TUI for hundreds of
milliseconds to seconds per press.

The fix routes navigation through the cache populated by the async
collector — no on-disk reads happen on the navigation path. This test
pins that invariant by monkeypatching the disk readers to raise.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.axe_display import AxeDisplayMixin, BgCmdSnapshot
from sase.ace.tui.widgets.bgcmd_list import (
    AxeParentItem,
    BgCmdItem,
    LumberjackItem,
)
from sase.axe.state import LumberjackMetrics, LumberjackStatus


def _status(name: str) -> LumberjackStatus:
    return LumberjackStatus(
        name=name,
        pid=1,
        started_at="2026-04-23T00:00:00",
        status="running",
        interval=60,
    )


class FakeAxeApp(AxeDisplayMixin):
    """Minimal stand-in exposing the axe-display surface for unit tests."""

    def __init__(self) -> None:
        self.current_tab = "axe"
        self.current_idx = 0
        self.refresh_interval = 10
        self.axe_running = True
        self._countdown_remaining = 10
        self._axe_status = None
        self._axe_metrics = None
        self._axe_output = ""
        self._axe_pinned_to_bottom = False
        self._axe_cmds_hidden = False
        self._axe_current_view = "axe"
        self._bgcmd_slots = []
        self._axe_lumberjack_names = ["hooks", "checks"]
        self._axe_lumberjack_idx = 0
        self._axe_items = [
            AxeParentItem(),
            LumberjackItem(name="hooks"),
            LumberjackItem(name="checks"),
            BgCmdItem(slot=1),
        ]
        self._bang_mode_active = False
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint = {}
        self._axe_first_load_done = True
        # Cache populated with fake entries so navigation can render.
        self._axe_lumberjack_statuses: dict[str, LumberjackStatus | None] = {
            "hooks": _status("hooks"),
            "checks": _status("checks"),
        }
        self._axe_lumberjack_metrics: dict[str, LumberjackMetrics | None] = {
            "hooks": LumberjackMetrics(chops_executed=3),
            "checks": LumberjackMetrics(chops_executed=1),
        }
        self._axe_lumberjack_log_tails = {
            "hooks": "hooks log\n",
            "checks": "checks log\n",
        }
        self._axe_bgcmd_details = {
            1: BgCmdSnapshot(info=None, running=True, output_tail="slot log\n"),
        }
        self._axe_detail_update_timer = None

    # Stubs for attributes / methods AxeDisplayMixin reaches for.
    def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
        return MagicMock()

    def set_timer(self, delay: float, callback: Any) -> Any:
        timer = MagicMock()
        timer.stop = MagicMock()
        # Remember scheduled callbacks so tests can drive the debounce.
        self._scheduled_callbacks.append((delay, callback))
        return timer

    _scheduled_callbacks: list[tuple[float, Any]] = []

    # No-op helpers called by refresh_axe_display.
    def _get_bgcmd_counts(self) -> tuple[int, int]:
        return (0, 0)


def test_navigation_does_not_read_from_disk() -> None:
    """A navigation-driven display refresh never touches disk readers.

    Monkeypatches every per-lumberjack and per-slot reader to raise. If
    navigation still funnels through them, these tests fail loudly rather
    than silently regressing the "instant j/k" property.
    """
    app = FakeAxeApp()
    app._scheduled_callbacks = []

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("navigation must not read from disk")

    with (
        patch("sase.ace.tui.actions.axe_display.read_lumberjack_status", _boom),
        patch("sase.ace.tui.actions.axe_display.read_lumberjack_metrics", _boom),
        patch("sase.ace.tui.actions.axe_display.read_lumberjack_log_tail", _boom),
        patch("sase.ace.tui.actions.axe_display.read_slot_output_tail", _boom),
        patch(
            "sase.ace.tui.actions.axe_display.get_slot_info",
            side_effect=_boom,
        ),
        patch(
            "sase.ace.tui.actions.axe_display.is_slot_running",
            side_effect=_boom,
        ),
    ):
        # Lumberjack view
        app.current_idx = 1
        app._refresh_axe_display_debounced()
        # Fire the debounced callback and verify no reader was hit.
        assert app._scheduled_callbacks, "debounce did not schedule a callback"
        _, callback = app._scheduled_callbacks[-1]
        app._scheduled_callbacks.clear()
        callback()

        # Parent-axe view
        app.current_idx = 0
        app._refresh_axe_display_debounced()
        _, callback = app._scheduled_callbacks[-1]
        app._scheduled_callbacks.clear()
        callback()

        # Bgcmd view: cache hit means no disk readers are touched.
        app.current_idx = 3
        app._refresh_axe_display_debounced()
        _, callback = app._scheduled_callbacks[-1]
        app._scheduled_callbacks.clear()
        callback()


def test_update_axe_tab_count_does_not_read_from_disk() -> None:
    """The AXE tab count derives from the cache, not per-name disk reads."""
    app = FakeAxeApp()

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("tab count must not read from disk")

    with patch("sase.ace.tui.actions.axe_display.read_lumberjack_status", _boom):
        app._update_axe_tab_count()
