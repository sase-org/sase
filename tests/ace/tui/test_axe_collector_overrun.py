"""Tests for axe collector overrun classification."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.axe_display import collect_axe_status_data
from sase.axe.config import ChopConfig, LumberjackConfig
from sase.axe.chop_overrun import ChopOverrun
from sase.axe.state import ChopRunEntry
from tests.ace.tui._axe_collector_helpers import (
    FakeAxeConfig as _FakeAxeConfig,
    fast_overrun as _fast_overrun,
    lumberjack_config as _lj_cfg,
    make_run_entry as _make_run_entry,
    make_status as _make_status,
)


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
            run_ratios=(0.5,),
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
