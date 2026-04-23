"""Tests for the axe async collector payload.

The TUI navigation path reads from caches that the collector populates in
a background thread. These tests pin the collector's contract: for every
lumberjack in the config and every active bgcmd slot, the returned
``_AxeCollectedData`` carries the status, metrics, log tail, and bgcmd
snapshot needed to paint the dashboard without any further disk reads.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.actions.axe_display import collect_axe_status_data
from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.axe.state import LumberjackMetrics, LumberjackStatus


class _FakeAxeConfig:
    def __init__(self, lumberjacks: dict[str, object]) -> None:
        self.lumberjacks = lumberjacks


def _make_status(name: str) -> LumberjackStatus:
    return LumberjackStatus(
        name=name,
        pid=123,
        started_at="2026-04-23T00:00:00",
        status="running",
        interval=60,
    )


def _make_metrics() -> LumberjackMetrics:
    return LumberjackMetrics(
        cycles_run=4,
        chops_executed=7,
        total_updates=2,
        errors_encountered=0,
    )


def _make_bgcmd_info() -> BackgroundCommandInfo:
    return BackgroundCommandInfo(
        command="sleep 1",
        project="proj",
        workspace_num=1,
        workspace_dir="/tmp/ws",
        started_at="2026-04-23T00:00:00",
    )


def test_collector_populates_all_cache_maps() -> None:
    """For every configured lumberjack and every active bgcmd slot, the
    collector records a cache entry. This is what the navigation path
    relies on to avoid disk I/O on each Ctrl+N / Ctrl+P.
    """
    config = _FakeAxeConfig({"hooks": None, "checks": None})
    bgcmd_info = _make_bgcmd_info()

    status_map = {"hooks": _make_status("hooks"), "checks": _make_status("checks")}
    metrics_map = {"hooks": _make_metrics(), "checks": _make_metrics()}
    log_map = {"hooks": "hooks log\n", "checks": "checks log\n"}

    with (
        patch(
            "sase.ace.tui.actions.axe_display._data.get_axe_process_module"
        ) as get_proc,
        patch("sase.ace.tui.actions.axe_display._data.read_metrics", return_value=None),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_output_log_tail",
            return_value="output\n",
        ),
        patch(
            "sase.axe.config.load_axe_config",
            return_value=config,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_status",
            side_effect=lambda name: status_map[name],
        ) as status_reader,
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_metrics",
            side_effect=lambda name: metrics_map[name],
        ) as metrics_reader,
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_log_tail",
            side_effect=lambda name, _n: log_map[name],
        ) as log_reader,
        patch(
            "sase.ace.tui.actions.axe_display._data.get_active_slots",
            return_value=[1],
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.get_slot_info",
            return_value=bgcmd_info,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.is_slot_running",
            return_value=True,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_slot_output_tail",
            return_value="slot output\n",
        ),
    ):
        proc = get_proc.return_value
        proc.is_axe_running.return_value = False
        proc.get_axe_status.return_value = None

        data = collect_axe_status_data()

    assert data.lumberjack_names == ["checks", "hooks"]
    # Per-lumberjack caches populated for every name
    assert set(data.lumberjack_statuses) == {"checks", "hooks"}
    assert set(data.lumberjack_metrics) == {"checks", "hooks"}
    assert set(data.lumberjack_log_tails) == {"checks", "hooks"}
    assert data.lumberjack_log_tails["hooks"] == "hooks log\n"
    assert data.lumberjack_statuses["hooks"].status == "running"  # type: ignore[union-attr]
    assert data.lumberjack_metrics["hooks"].chops_executed == 7  # type: ignore[union-attr]

    # Bgcmd snapshot populated for the active slot
    assert set(data.bgcmd_details) == {1}
    snap = data.bgcmd_details[1]
    assert snap.running is True
    assert snap.output_tail == "slot output\n"
    assert snap.info is bgcmd_info

    # Exactly one round-trip per lumberjack (not per navigation keypress)
    assert status_reader.call_count == 2
    assert metrics_reader.call_count == 2
    assert log_reader.call_count == 2
