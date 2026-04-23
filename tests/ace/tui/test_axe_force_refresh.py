"""`y` on the Axe tab should repaint the focused item from fresh disk data.

The full-fleet refresh may be slow (many lumberjacks, cold caches). When
the user hits `y`, they care about *what they're looking at right now* —
so the targeted refresh path re-reads only the currently selected item
and updates its cache entry, independent of the full-fleet refresh.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.ace.tui.actions.axe_display import AxeDisplayMixin, BgCmdSnapshot
from sase.ace.tui.widgets.bgcmd_list import (
    AxeParentItem,
    BgCmdItem,
    LumberjackItem,
)
from sase.axe.state import LumberjackMetrics, LumberjackStatus


def _status(name: str, kind: str = "running") -> LumberjackStatus:
    return LumberjackStatus(
        name=name,
        pid=1,
        started_at="2026-04-23T00:00:00",
        status=kind,  # type: ignore[arg-type]
        interval=60,
    )


class FakeAxeApp(AxeDisplayMixin):
    def __init__(self) -> None:
        self.current_tab = "axe"
        self.current_idx = 1  # select the "hooks" lumberjack
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
        self._axe_lumberjack_names = ["hooks"]
        self._axe_lumberjack_idx = 0
        self._axe_items = [
            AxeParentItem(),
            LumberjackItem(name="hooks"),
            BgCmdItem(slot=1),
        ]
        self._bang_mode_active = False
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint = {}
        self._axe_first_load_done = True
        self._axe_lumberjack_statuses: dict[str, LumberjackStatus | None] = {
            "hooks": _status("hooks", "stopped"),  # cached value before refresh
        }
        self._axe_lumberjack_metrics: dict[str, LumberjackMetrics | None] = {
            "hooks": LumberjackMetrics(chops_executed=0),
        }
        self._axe_lumberjack_log_tails = {"hooks": "stale\n"}
        self._axe_bgcmd_details = {
            1: BgCmdSnapshot(info=None, running=False, output_tail="old\n"),
        }
        self._axe_detail_update_timer = None
        self._refreshed = 0

    def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
        return MagicMock()

    def _refresh_axe_display(self) -> None:  # type: ignore[override]
        self._refreshed += 1

    def _get_bgcmd_counts(self) -> tuple[int, int]:
        return (0, 0)


@pytest.mark.asyncio
async def test_targeted_refresh_updates_selected_lumberjack() -> None:
    """A `y`-driven targeted refresh updates the cache entry for the
    selected lumberjack and triggers a repaint — without waiting for the
    full-fleet refresh to complete.
    """
    app = FakeAxeApp()

    fresh_status = _status("hooks", "running")
    fresh_metrics = LumberjackMetrics(chops_executed=99)

    with (
        patch(
            "sase.ace.tui.actions.axe_display._loaders.read_lumberjack_status",
            return_value=fresh_status,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._loaders.read_lumberjack_metrics",
            return_value=fresh_metrics,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._loaders.read_lumberjack_log_tail",
            return_value="fresh log\n",
        ),
    ):
        await app._refresh_selected_axe_item_async()

    assert app._axe_lumberjack_statuses["hooks"].status == "running"  # type: ignore[union-attr]
    assert app._axe_lumberjack_metrics["hooks"].chops_executed == 99  # type: ignore[union-attr]
    assert app._axe_lumberjack_log_tails["hooks"] == "fresh log\n"
    assert app._refreshed == 1


@pytest.mark.asyncio
async def test_targeted_refresh_updates_selected_bgcmd_slot() -> None:
    """When a bgcmd row is selected, the targeted refresh rewrites that
    slot's snapshot."""
    app = FakeAxeApp()
    app.current_idx = 2  # BgCmdItem(slot=1)

    with (
        patch(
            "sase.ace.tui.actions.axe_display._loaders.get_slot_info",
            return_value=None,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._loaders.is_slot_running",
            return_value=True,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._loaders.read_slot_output_tail",
            return_value="refreshed\n",
        ),
    ):
        await app._refresh_selected_axe_item_async()

    snap = app._axe_bgcmd_details[1]
    assert snap.running is True
    assert snap.output_tail == "refreshed\n"
    assert app._refreshed == 1


@pytest.mark.asyncio
async def test_targeted_refresh_is_non_blocking() -> None:
    """The selected-item refresh hands disk reads to a worker thread so
    the event loop stays responsive while they run."""
    app = FakeAxeApp()

    import time

    def slow_status(_name: str) -> LumberjackStatus:
        time.sleep(0.05)
        return _status("hooks")

    with (
        patch(
            "sase.ace.tui.actions.axe_display._loaders.read_lumberjack_status",
            side_effect=slow_status,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._loaders.read_lumberjack_metrics",
            return_value=LumberjackMetrics(),
        ),
        patch(
            "sase.ace.tui.actions.axe_display._loaders.read_lumberjack_log_tail",
            return_value="",
        ),
    ):
        task = asyncio.create_task(app._refresh_selected_axe_item_async())
        # While the worker is sleeping, we must still be able to progress
        # other coroutines.
        await asyncio.sleep(0.01)
        assert not task.done()
        await task
