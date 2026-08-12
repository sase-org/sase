"""Tests for the axe async collector payload.

The TUI navigation path reads from caches that the collector populates in
a background thread. These tests pin the collector's contract: for every
lumberjack in the config and every active bgcmd slot, the returned
``_AxeCollectedData`` carries the status, metrics, log tail, and bgcmd
snapshot needed to paint the dashboard without any further disk reads.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.axe_display import collect_axe_status_data
from sase.ace.tui.bgcmd import BackgroundCommandInfo
from sase.axe.config import (
    _AxeConfigDiagnostic,
    AxeConfigError,
    ChopConfig,
    LumberjackConfig,
)
from sase.axe.chop_overrun import ChopOverrun
from sase.axe.state import (
    ChopRunEntry,
    LumberjackMetrics,
    LumberjackStatus,
)


class _FakeAxeConfig:
    def __init__(self, lumberjacks: dict[str, LumberjackConfig]) -> None:
        self.lumberjacks = lumberjacks


def _make_status(name: str, *, interval: int = 60) -> LumberjackStatus:
    return LumberjackStatus(
        name=name,
        pid=123,
        started_at="2026-04-23T00:00:00",
        status="running",
        interval=interval,
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


def _lj_cfg(
    name: str, chop_names: list[str], *, interval: int = 60
) -> LumberjackConfig:
    return LumberjackConfig(
        name=name,
        description=f"{name} lane description\n\n{name} lane body",
        description_summary=f"{name} lane description",
        description_body=f"{name} lane body",
        interval=interval,
        chops=[
            ChopConfig(
                name=c,
                description=f"{c} desc\n\n{c} body",
                description_summary=f"{c} desc",
                description_body=f"{c} body",
            )
            for c in chop_names
        ],
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


def _fast_overrun() -> ChopOverrun:
    return ChopOverrun(
        level="over",
        sampled_runs=1,
        over_runs=1,
        worst_ratio=1.5,
        worst_blocking_ms=90000,
        latest_ratio=1.5,
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
    assert data.chop_snapshots[("hooks", "slow")].description == (
        "slow desc\n\nslow body"
    )
    assert data.chop_snapshots[("hooks", "slow")].description_summary == "slow desc"
    assert data.chop_snapshots[("hooks", "slow")].description_body == "slow body"

    # The chop with recorded history carries up to MAX (10) newest-first
    # entries, paired with their bounded output tails.
    fast_snap = data.chop_snapshots[("hooks", "fast")]
    assert [r.entry.run_id for r in fast_snap.runs] == fast_runs
    assert fast_snap.runs[0].output_tail == f"{fast_runs[0]} output\n"
    assert fast_snap.description == "fast desc\n\nfast body"
    assert fast_snap.description_summary == "fast desc"
    assert fast_snap.description_body == "fast body"

    # Composite per-lumberjack snapshot mirrors the dicts above.
    hooks_snap = data.lumberjack_snapshots["hooks"]
    assert hooks_snap.description == "hooks lane description\n\nhooks lane body"
    assert hooks_snap.description_summary == "hooks lane description"
    assert hooks_snap.description_body == "hooks lane body"
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


def test_collector_classifies_against_runtime_interval() -> None:
    """Runtime status interval wins over config when both are available."""
    config = _FakeAxeConfig({"hooks": _lj_cfg("hooks", ["slow"], interval=120)})
    run = ChopRunEntry(
        run_id="20260511T100100_000000",
        lumberjack_name="hooks",
        chop_name="slow",
        started_at="2026-05-11T10:01:00",
        finished_at="2026-05-11T10:02:01",
        duration_ms=61000,
        status="success",
    )
    seen: list[tuple[int, int]] = []

    def _classify(
        *,
        now: datetime,
        interval_seconds: int,
        runs: Sequence[ChopRunEntry],
    ) -> ChopOverrun:
        assert now.tzinfo is not None
        seen.append((interval_seconds, runs[0].duration_ms))
        return _fast_overrun()

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
            return_value=_make_status("hooks", interval=60),
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
            return_value=[run.run_id],
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run",
            return_value=run,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run_log_tail",
            return_value="slow output\n",
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.discover_chop_script",
            return_value=Path("/tmp/sase-chop-slow"),
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.classify_chop_overrun",
            side_effect=_classify,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.get_active_slots", return_value=[]
        ),
    ):
        proc = get_proc.return_value
        proc.is_axe_running.return_value = False
        proc.get_axe_status.return_value = None

        data = collect_axe_status_data()

    snap = data.chop_snapshots[("hooks", "slow")]
    assert snap.interval_seconds == 60
    assert snap.interval_source == "runtime"
    assert snap.overrun is not None
    assert snap.overrun.level == "over"
    assert seen == [(60, 61000)]
    assert data.lumberjack_snapshots["hooks"].overrun_chop_count == 1
    assert data.lumberjack_snapshots["hooks"].intermittent_chop_count == 0


def test_collector_falls_back_to_config_interval_without_runtime_status() -> None:
    """A stopped or absent lumberjack status classifies against config."""
    config = _FakeAxeConfig({"hooks": _lj_cfg("hooks", ["slow"], interval=45)})
    run = _make_run_entry("hooks", "slow", "20260511T100100_000000")
    seen: list[int] = []

    def _classify(
        *,
        now: datetime,
        interval_seconds: int,
        runs: Sequence[ChopRunEntry],
    ) -> ChopOverrun:
        assert now.tzinfo is not None
        assert len(runs) == 1
        seen.append(interval_seconds)
        return ChopOverrun(
            level="intermittent",
            sampled_runs=2,
            over_runs=1,
            worst_ratio=2.0,
            worst_blocking_ms=90000,
            latest_ratio=0.5,
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
            return_value=[run.run_id],
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run",
            return_value=run,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run_log_tail",
            return_value="slow output\n",
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.discover_chop_script",
            return_value=Path("/tmp/sase-chop-slow"),
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.classify_chop_overrun",
            side_effect=_classify,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.get_active_slots", return_value=[]
        ),
    ):
        proc = get_proc.return_value
        proc.is_axe_running.return_value = False
        proc.get_axe_status.return_value = None

        data = collect_axe_status_data()

    snap = data.chop_snapshots[("hooks", "slow")]
    assert snap.interval_seconds == 45
    assert snap.interval_source == "config"
    assert snap.overrun is not None
    assert snap.overrun.level == "intermittent"
    assert seen == [45]
    assert data.lumberjack_snapshots["hooks"].overrun_chop_count == 0
    assert data.lumberjack_snapshots["hooks"].intermittent_chop_count == 1


def test_collector_does_not_classify_disabled_chop() -> None:
    """Disabled chops carry config metadata but never get an overrun verdict."""
    config = _FakeAxeConfig(
        {
            "hooks": LumberjackConfig(
                name="hooks",
                description="",
                interval=60,
                chops=[
                    ChopConfig(
                        name="slow",
                        enabled=False,
                        description="slow desc",
                        description_summary="slow desc",
                    )
                ],
            )
        }
    )
    run = _make_run_entry("hooks", "slow", "20260511T100100_000000")

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
            return_value=_make_status("hooks"),
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
            return_value=[run.run_id],
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run",
            return_value=run,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run_log_tail",
            return_value="slow output\n",
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.classify_chop_overrun",
            side_effect=AssertionError("disabled chops should not be classified"),
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.get_active_slots", return_value=[]
        ),
    ):
        proc = get_proc.return_value
        proc.is_axe_running.return_value = False
        proc.get_axe_status.return_value = None

        data = collect_axe_status_data()

    snap = data.chop_snapshots[("hooks", "slow")]
    assert snap.enabled is False
    assert snap.config_status == "disabled"
    assert snap.interval_seconds == 60
    assert snap.interval_source == "runtime"
    assert snap.overrun is None
    assert data.lumberjack_snapshots["hooks"].overrun_chop_count == 0


def test_collector_degrades_when_overrun_binding_fails() -> None:
    """Classifier failures leave the rest of the chop snapshot intact."""
    config = _FakeAxeConfig({"hooks": _lj_cfg("hooks", ["slow"])})
    run = _make_run_entry("hooks", "slow", "20260511T100100_000000")

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
            return_value=_make_status("hooks"),
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
            return_value=[run.run_id],
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run",
            return_value=run,
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.read_chop_run_log_tail",
            return_value="slow output\n",
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.discover_chop_script",
            return_value=Path("/tmp/sase-chop-slow"),
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.classify_chop_overrun",
            side_effect=RuntimeError("binding unavailable"),
        ),
        patch(
            "sase.ace.tui.actions.axe_display._data.get_active_slots", return_value=[]
        ),
    ):
        proc = get_proc.return_value
        proc.is_axe_running.return_value = False
        proc.get_axe_status.return_value = None

        data = collect_axe_status_data()

    snap = data.chop_snapshots[("hooks", "slow")]
    assert [run_snapshot.entry.run_id for run_snapshot in snap.runs] == [run.run_id]
    assert snap.runs[0].output_tail == "slow output\n"
    assert snap.description == "slow desc\n\nslow body"
    assert snap.interval_seconds == 60
    assert snap.interval_source == "runtime"
    assert snap.overrun is None
    assert data.lumberjack_snapshots["hooks"].overrun_chop_count == 0
