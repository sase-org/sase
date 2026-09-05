"""Phase 4: live collector and dashboard behavior for running chop runs.

Three invariants are exercised here:

1. A new run prepended to the cached history shifts pinned offsets so the
   user stays on the same run_id rather than being yanked back to newest.
2. The per-second live tick schedules a targeted refresh when (and only
   when) the selected chop's newest run is still running.
3. Navigation paths repaint from the cache even when a running run is
   present, never hitting disk readers.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from sase.ace.tui.actions.axe_display import (
    AxeDisplayMixin,
    BgCmdSnapshot,
    ChopRunSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.ace.tui.actions.axe_display._data import AxeCollectedData
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.widgets.bgcmd_list import (
    BgCmdItem,
    ChopItem,
    LumberjackItem,
)
from sase.axe.state import ChopRunEntry, LumberjackMetrics, LumberjackStatus


def _entry(
    run_id: str,
    *,
    status: str = "success",
    finished_at: str | None = "2026-05-11T00:00:01",
    pid: int | None = None,
) -> ChopRunEntry:
    return ChopRunEntry(
        run_id=run_id,
        lumberjack_name="hooks",
        chop_name="fast",
        started_at="2026-05-11T00:00:00",
        finished_at=finished_at,
        duration_ms=0 if status == "running" else 1000,
        status=status,  # type: ignore[arg-type]
        pid=pid,
    )


def _run_snap(run_id: str, **kwargs: Any) -> ChopRunSnapshot:
    return ChopRunSnapshot(entry=_entry(run_id, **kwargs), output_tail="")


def _chop_snap(*runs: ChopRunSnapshot) -> ChopSnapshot:
    return ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fast",
        description="",
        runs=list(runs),
    )


def _status(name: str = "hooks") -> LumberjackStatus:
    return LumberjackStatus(
        name=name,
        pid=1,
        started_at="2026-05-11T00:00:00",
        status="running",
        interval=60,
    )


class _Fake(AxeDisplayMixin):
    """Minimal AXE-tab harness used by the live-run reconciliation tests."""

    def __init__(self, runs: list[ChopRunSnapshot]) -> None:
        self.current_tab: Any = "axe"
        self.current_idx = 1  # ChopItem
        self.refresh_interval = 10
        self.axe_running = True
        self._countdown_remaining = 10
        self._axe_status = None
        self._axe_metrics = None
        self._axe_output = ""
        self._axe_pinned_to_bottom = False
        self._axe_cmds_hidden = False
        self._axe_current_view: Any = "axe"
        self._bgcmd_slots: list[Any] = []
        self._axe_lumberjack_names = ["hooks"]
        self._axe_lumberjack_idx = 0
        self._axe_items = [
            LumberjackItem(name="hooks"),
            ChopItem(lumberjack_name="hooks", chop_name="fast"),
            BgCmdItem(slot=1),
        ]
        self._axe_chop_selection: tuple[str, str] | None = ("hooks", "fast")
        self._bang_mode_active = False
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._axe_first_load_done = True
        self._axe_lumberjack_statuses = {"hooks": _status()}
        self._axe_lumberjack_metrics = {"hooks": LumberjackMetrics()}
        self._axe_lumberjack_log_tails = {"hooks": ""}
        self._axe_bgcmd_details: dict[int, BgCmdSnapshot] = {}
        self._axe_lumberjack_chop_names = {"hooks": ["fast"]}
        self._axe_chop_snapshots = {("hooks", "fast"): _chop_snap(*runs)}
        self._axe_lumberjack_snapshots = {
            "hooks": LumberjackSnapshot(
                name="hooks",
                status=_status(),
                metrics=LumberjackMetrics(),
                log_tail="",
                chops=[self._axe_chop_snapshots[("hooks", "fast")]],
            ),
        }
        self._axe_chop_run_offsets: dict[tuple[str, str], int] = {}
        self._axe_detail_debouncer = DetailPanelDebouncer(self)  # type: ignore[arg-type]
        self.refresh_calls = 0
        self.scheduled_targeted_refresh = 0

    def _refresh_axe_display(self) -> None:  # type: ignore[override]
        self.refresh_calls += 1

    def _schedule_targeted_axe_refresh(self) -> None:  # type: ignore[override]
        self.scheduled_targeted_refresh += 1

    def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
        return MagicMock()

    def _get_bgcmd_counts(self) -> tuple[int, int]:
        return (0, 0)


def test_pin_shifts_when_new_run_prepended() -> None:
    """Pinned offset stays on the same run_id when a new run prepends."""
    app = _Fake([_run_snap("r3"), _run_snap("r2"), _run_snap("r1")])
    # Pin to r2 (offset=1).
    app._axe_chop_run_offsets[("hooks", "fast")] = 1

    new_snap = _chop_snap(
        _run_snap("r4", status="running", finished_at=None, pid=42),
        _run_snap("r3"),
        _run_snap("r2"),
        _run_snap("r1"),
    )
    app._reconcile_chop_run_offsets({("hooks", "fast"): new_snap})

    # User was looking at r2 — now at index 2 in the new history.
    assert app._axe_chop_run_offsets[("hooks", "fast")] == 2


def test_pin_dropped_when_run_disappears() -> None:
    """Pinned offset is removed when its run_id no longer exists."""
    app = _Fake([_run_snap("r3"), _run_snap("r2"), _run_snap("r1")])
    app._axe_chop_run_offsets[("hooks", "fast")] = 2  # pinned to r1

    # New snapshot lost r1 (pruning, config rename, etc).
    new_snap = _chop_snap(_run_snap("r4"), _run_snap("r3"), _run_snap("r2"))
    app._reconcile_chop_run_offsets({("hooks", "fast"): new_snap})

    assert ("hooks", "fast") not in app._axe_chop_run_offsets


def test_pin_dropped_when_run_becomes_newest() -> None:
    """A pinned offset that lands on index 0 falls back to newest-tracking."""
    app = _Fake([_run_snap("r3"), _run_snap("r2"), _run_snap("r1")])
    app._axe_chop_run_offsets[("hooks", "fast")] = 2  # pinned to r1

    new_snap = _chop_snap(_run_snap("r1"))
    app._reconcile_chop_run_offsets({("hooks", "fast"): new_snap})

    assert ("hooks", "fast") not in app._axe_chop_run_offsets


def test_unpinned_chop_with_new_run_stays_on_newest() -> None:
    """Offset 0 (auto-track newest) is never written to by reconciliation."""
    app = _Fake([_run_snap("r1")])
    new_snap = _chop_snap(
        _run_snap("r2", status="running", finished_at=None), _run_snap("r1")
    )
    app._reconcile_chop_run_offsets({("hooks", "fast"): new_snap})
    assert ("hooks", "fast") not in app._axe_chop_run_offsets


def test_live_tick_schedules_targeted_refresh_when_running() -> None:
    """The live tick fires only when the selected chop's newest run is active."""
    app = _Fake(
        [
            _run_snap("running", status="running", finished_at=None, pid=42),
            _run_snap("older"),
        ]
    )

    app._axe_live_tick()
    assert app.scheduled_targeted_refresh == 1


def test_live_tick_quiet_when_no_running_run() -> None:
    """No targeted refresh fires when nothing is streaming."""
    app = _Fake([_run_snap("done")])
    app._axe_live_tick()
    assert app.scheduled_targeted_refresh == 0


def test_live_tick_quiet_off_axe_tab() -> None:
    """The live tick is inert when the user has navigated away from AXE."""
    app = _Fake(
        [
            _run_snap("running", status="running", finished_at=None),
        ]
    )
    app.current_tab = "agents"
    app._axe_live_tick()
    assert app.scheduled_targeted_refresh == 0


def test_live_tick_quiet_on_lumberjack_or_bgcmd_row() -> None:
    """A lumberjack / bgcmd selection never triggers the chop live tick."""
    app = _Fake(
        [
            _run_snap("running", status="running", finished_at=None),
        ]
    )
    app._axe_chop_selection = None
    app._axe_live_tick()
    assert app.scheduled_targeted_refresh == 0


def test_navigation_disk_free_with_running_run() -> None:
    """Navigation must repaint from cache even when a run is streaming."""
    app = _Fake(
        [
            _run_snap("running", status="running", finished_at=None, pid=42),
            _run_snap("older"),
        ]
    )

    def _boom(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("navigation must not read from disk")

    with (
        patch("sase.ace.tui.actions.axe_display._data.read_chop_run_index", _boom),
        patch("sase.ace.tui.actions.axe_display._data.read_chop_run", _boom),
        patch("sase.ace.tui.actions.axe_display._data.read_chop_run_log_tail", _boom),
        patch(
            "sase.ace.tui.actions.axe_display._loader_refresh.read_lumberjack_status",
            _boom,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._loader_refresh.read_lumberjack_metrics",
            _boom,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._loader_refresh.read_lumberjack_log_tail",
            _boom,
        ),
    ):
        # The live tick schedules a *targeted* refresh; it must not perform
        # any reads on its own.
        app._axe_live_tick()
        # Resolving the offset against a running run is cache-only.
        assert app._axe_resolve_chop_run_offset(("hooks", "fast")) == 0


def test_apply_axe_status_data_reconciles_pinned_offsets() -> None:
    """Applying a fresh collector payload preserves the pinned run_id."""
    app = _Fake([_run_snap("r3"), _run_snap("r2"), _run_snap("r1")])
    app._axe_chop_run_offsets[("hooks", "fast")] = 1  # pinned to r2

    new_snap = _chop_snap(
        _run_snap("r4", status="running", finished_at=None),
        _run_snap("r3"),
        _run_snap("r2"),
        _run_snap("r1"),
    )
    data = AxeCollectedData(
        axe_running=True,
        axe_status=None,
        axe_metrics=None,
        axe_output="",
        lumberjack_names=["hooks"],
        bgcmd_slots=[],
        lumberjack_statuses={"hooks": _status()},
        lumberjack_metrics={"hooks": LumberjackMetrics()},
        lumberjack_log_tails={"hooks": ""},
        bgcmd_details={},
        lumberjack_chop_names={"hooks": ["fast"]},
        chop_snapshots={("hooks", "fast"): new_snap},
        lumberjack_snapshots={
            "hooks": LumberjackSnapshot(
                name="hooks",
                status=_status(),
                metrics=LumberjackMetrics(),
                log_tail="",
                chops=[new_snap],
            )
        },
    )

    # Stub the hooks _apply_axe_status_data reaches for so we can drive it
    # without a full Textual app.
    def _noop(*_a: Any, **_kw: Any) -> None:
        return None

    app._maybe_end_startup_stopwatch = _noop  # type: ignore[attr-defined]
    app._set_axe_starting = _noop  # type: ignore[attr-defined]
    app._set_axe_restarting = _noop  # type: ignore[attr-defined]
    app._set_axe_stopping = _noop  # type: ignore[attr-defined]
    app._update_axe_keybinding = _noop  # type: ignore[attr-defined]
    app._update_bgcmd_count = _noop  # type: ignore[attr-defined]
    app._build_axe_items = _noop  # type: ignore[attr-defined]

    app._apply_axe_status_data(data)

    assert app._axe_chop_run_offsets[("hooks", "fast")] == 2


def test_apply_summary_payload_preserves_chop_snapshots() -> None:
    """Off-tab header ticks must not wipe the last full chop-history cache."""
    app = _Fake([_run_snap("r1")])
    previous = app._axe_chop_snapshots[("hooks", "fast")]
    app._axe_output = "stale axe\n"
    app._axe_lumberjack_log_tails["hooks"] = "stale jack\n"
    data = AxeCollectedData(
        axe_running=True,
        axe_status=None,
        axe_metrics=None,
        axe_output="new axe log\n",
        lumberjack_names=["hooks"],
        bgcmd_slots=[],
        lumberjack_statuses={"hooks": _status()},
        lumberjack_metrics={"hooks": LumberjackMetrics(chops_executed=9)},
        lumberjack_log_tails={"hooks": "new log\n"},
        bgcmd_details={},
        lumberjack_chop_names={"hooks": ["fast"]},
        chop_snapshots={},
        lumberjack_snapshots={},
        include_full_snapshots=False,
    )

    def _noop(*_a: Any, **_kw: Any) -> None:
        return None

    app._maybe_end_startup_stopwatch = _noop  # type: ignore[attr-defined]
    app._set_axe_starting = _noop  # type: ignore[attr-defined]
    app._set_axe_restarting = _noop  # type: ignore[attr-defined]
    app._set_axe_stopping = _noop  # type: ignore[attr-defined]
    app._update_axe_keybinding = _noop  # type: ignore[attr-defined]
    app._update_bgcmd_count = _noop  # type: ignore[attr-defined]
    app._build_axe_items = _noop  # type: ignore[attr-defined]

    app._apply_axe_status_data(data)

    assert app._axe_chop_snapshots[("hooks", "fast")] is previous
    assert app._axe_output == "stale axe\n"
    assert app._axe_lumberjack_log_tails["hooks"] == "stale jack\n"
    assert app._axe_lumberjack_metrics["hooks"].chops_executed == 9
    jack_metrics = app._axe_lumberjack_snapshots["hooks"].metrics
    assert jack_metrics is not None
    assert jack_metrics.chops_executed == 9
