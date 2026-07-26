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
from sase.axe.config import (
    _AxeConfigDiagnostic,
    AxeConfigError,
    ChopConfig,
    LumberjackConfig,
)
from sase.axe.state import (
    ChopRunEntry,
    LumberjackMetrics,
    LumberjackStatus,
)


class _FakeAxeConfig:
    def __init__(self, lumberjacks: dict[str, LumberjackConfig]) -> None:
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


def _lj_cfg(name: str, chop_names: list[str]) -> LumberjackConfig:
    return LumberjackConfig(
        name=name,
        description=f"{name} lane description",
        interval=60,
        chops=[ChopConfig(name=c, description=f"{c} desc") for c in chop_names],
    )


def _make_run_entry(lj: str, chop: str, run_id: str) -> ChopRunEntry:
    return ChopRunEntry(
        run_id=run_id,
        lumberjack_name=lj,
        chop_name=chop,
        started_at="2026-05-11T10:00:00",
        finished_at="2026-05-11T10:00:01",
        duration_ms=1000,
        status="success",
        exit_code=0,
        output_bytes=10,
        output_log=f"{run_id}.log",
    )


def test_collector_degrades_invalid_axe_config_to_status() -> None:
    """Invalid config is visible in the pane instead of escaping the refresh."""
    error = AxeConfigError(
        [
            _AxeConfigDiagnostic(
                code="unknown_key",
                path="axe.extra",
                message="unsupported setting",
            )
        ]
    )

    with (
        patch(
            "sase.ace.tui.actions.axe_display._data.get_axe_process_module"
        ) as get_proc,
        patch("sase.ace.tui.actions.axe_display._data.read_metrics", return_value=None),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_output_log_tail",
            return_value="",
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.get_active_slots",
            return_value=[],
        ),
        patch("sase.axe.config.load_axe_config") as load_config,
    ):
        proc = get_proc.return_value
        proc.is_axe_running.return_value = True
        proc.get_axe_status.side_effect = error

        data = collect_axe_status_data()

    assert data.axe_running is True
    assert data.axe_status is None
    assert data.lumberjack_names == []
    assert data.degraded_status is not None
    assert data.degraded_status.message == (
        "axe config invalid: [unknown_key] axe.extra: unsupported setting"
    )
    load_config.assert_not_called()


def test_collector_populates_all_cache_maps() -> None:
    """For every configured lumberjack and every active bgcmd slot, the
    collector records a cache entry. This is what the navigation path
    relies on to avoid disk I/O on each Ctrl+N / Ctrl+P.
    """
    config = _FakeAxeConfig(
        {
            "hooks": _lj_cfg("hooks", ["fast", "slow"]),
            "checks": _lj_cfg("checks", []),
        }
    )
    bgcmd_info = _make_bgcmd_info()

    status_map = {"hooks": _make_status("hooks"), "checks": _make_status("checks")}
    metrics_map = {"hooks": _make_metrics(), "checks": _make_metrics()}
    log_map = {"hooks": "hooks log\n", "checks": "checks log\n"}

    # Chop run-history wiring: ``hooks/fast`` has two recorded runs;
    # everyone else has no recorded history yet.
    fast_runs = ["20260511T100100_000000", "20260511T100000_000000"]
    fast_entries = {rid: _make_run_entry("hooks", "fast", rid) for rid in fast_runs}

    def _fake_run_index(lj: str, chop: str) -> list[str]:
        if (lj, chop) == ("hooks", "fast"):
            return fast_runs
        return []

    def _fake_read_run(_lj: str, _chop: str, run_id: str) -> ChopRunEntry | None:
        return fast_entries.get(run_id)

    def _fake_read_run_log(_lj: str, _chop: str, run_id: str, _lines: int) -> str:
        return f"{run_id} output\n"

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
            side_effect=lambda name, _lines: log_map[name],
        ) as log_reader,
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run_index",
            side_effect=_fake_run_index,
        ) as run_index_reader,
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run",
            side_effect=_fake_read_run,
        ) as run_reader,
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run_log_tail",
            side_effect=_fake_read_run_log,
        ) as run_log_reader,
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

    # Chop names recorded in config order for every lumberjack.
    assert data.lumberjack_chop_names == {
        "checks": [],
        "hooks": ["fast", "slow"],
    }
    # Every configured chop has a snapshot, even with no history. The
    # snapshot's ``runs`` list is empty for unrun chops — that is the
    # invariant the dashboard relies on for an empty-state path.
    assert set(data.chop_snapshots) == {
        ("hooks", "fast"),
        ("hooks", "slow"),
    }
    assert data.chop_snapshots[("hooks", "slow")].runs == []
    assert data.chop_snapshots[("hooks", "slow")].description == "slow desc"

    # The chop with recorded history carries up to MAX (10) newest-first
    # entries, paired with their bounded output tails.
    fast_snap = data.chop_snapshots[("hooks", "fast")]
    assert [r.entry.run_id for r in fast_snap.runs] == fast_runs
    assert fast_snap.runs[0].output_tail == f"{fast_runs[0]} output\n"
    assert fast_snap.description == "fast desc"

    # Composite per-lumberjack snapshot mirrors the dicts above.
    hooks_snap = data.lumberjack_snapshots["hooks"]
    assert hooks_snap.description == "hooks lane description"
    assert hooks_snap.status is status_map["hooks"]
    assert hooks_snap.metrics is metrics_map["hooks"]
    assert hooks_snap.log_tail == "hooks log\n"
    assert [c.chop_name for c in hooks_snap.chops] == ["fast", "slow"]

    # Run-history readers are called once per configured chop and once
    # per recorded run respectively — not once per navigation keypress.
    assert run_index_reader.call_count == 2
    assert run_reader.call_count == len(fast_runs)
    assert run_log_reader.call_count == len(fast_runs)


def test_collector_carries_running_run_through_snapshot() -> None:
    """A chop with a ``running`` newest run keeps the active entry plus
    its in-progress log tail in the cached snapshot — the dashboard reads
    both straight from this snapshot without hitting disk again.
    """
    config = _FakeAxeConfig({"hooks": _lj_cfg("hooks", ["fast"])})

    running_id = "20260511T100200_000000"
    finished_id = "20260511T100100_000000"
    running_entry = ChopRunEntry(
        run_id=running_id,
        lumberjack_name="hooks",
        chop_name="fast",
        started_at="2026-05-11T10:02:00",
        finished_at=None,
        duration_ms=0,
        status="running",
        pid=99999,
        source="manual",
    )
    finished_entry = _make_run_entry("hooks", "fast", finished_id)

    def _fake_run_index(_lj: str, _chop: str) -> list[str]:
        return [running_id, finished_id]

    def _fake_read_run(_lj: str, _chop: str, run_id: str) -> ChopRunEntry | None:
        return {running_id: running_entry, finished_id: finished_entry}.get(run_id)

    def _fake_read_run_log(_lj: str, _chop: str, run_id: str, _lines: int) -> str:
        if run_id == running_id:
            return "first line of live output\n"
        return "older output\n"

    with (
        patch(
            "sase.ace.tui.actions.axe_display._data.get_axe_process_module"
        ) as get_proc,
        patch("sase.ace.tui.actions.axe_display._data.read_metrics", return_value=None),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_output_log_tail",
            return_value="",
        ),
        patch("sase.axe.config.load_axe_config", return_value=config),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_status",
            return_value=None,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_metrics",
            return_value=None,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_log_tail",
            return_value="",
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run_index",
            side_effect=_fake_run_index,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run",
            side_effect=_fake_read_run,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run_log_tail",
            side_effect=_fake_read_run_log,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.get_active_slots", return_value=[]
        ),
    ):
        proc = get_proc.return_value
        proc.is_axe_running.return_value = False
        proc.get_axe_status.return_value = None

        data = collect_axe_status_data()

    fast = data.chop_snapshots[("hooks", "fast")]
    assert [r.entry.run_id for r in fast.runs] == [running_id, finished_id]
    assert fast.runs[0].entry.status == "running"
    assert fast.runs[0].entry.finished_at is None
    assert fast.runs[0].entry.pid == 99999
    assert fast.runs[0].output_tail == "first line of live output\n"


def test_collector_records_empty_history_for_missing_chops() -> None:
    """A lumberjack with chops but no recorded run history still gets a
    ``ChopSnapshot`` per configured chop, with an empty ``runs`` list.

    The empty-state contract is what the dashboard renders against on
    first paint, so the collector must always emit a snapshot — never
    omit the key.
    """
    config = _FakeAxeConfig({"hooks": _lj_cfg("hooks", ["only"])})

    with (
        patch(
            "sase.ace.tui.actions.axe_display._data.get_axe_process_module"
        ) as get_proc,
        patch("sase.ace.tui.actions.axe_display._data.read_metrics", return_value=None),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_output_log_tail",
            return_value="",
        ),
        patch("sase.axe.config.load_axe_config", return_value=config),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_status",
            return_value=None,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_metrics",
            return_value=None,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_lumberjack_log_tail",
            return_value="",
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run_index",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.get_active_slots", return_value=[]
        ),
    ):
        proc = get_proc.return_value
        proc.is_axe_running.return_value = False
        proc.get_axe_status.return_value = None

        data = collect_axe_status_data()

    assert data.chop_snapshots[("hooks", "only")].runs == []
