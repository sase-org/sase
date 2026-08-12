"""Run-state and pacing data builders for AXE PNG snapshot tests."""

from __future__ import annotations

from sase.ace.tui.actions.axe_display._data import (
    AxeCollectedData,
    ChopRunSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.axe.chop_overrun import ChopOverrun
from sase.axe.state import ChopRunEntry, LumberjackMetrics, LumberjackStatus
from tests.ace.tui.visual._ace_axe_png_snapshot_builders import (
    make_chop_run,
    make_lumberjack_status,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import axe_collected_data


def axe_lumberjack_error_data() -> AxeCollectedData:
    """Build a single lumberjack in an error state with one failed run."""
    failed_chop = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fast_lint",
        description="fast lint",
        runs=[
            make_chop_run(
                "hooks",
                "fast_lint",
                run_id="20260509T100000_000000",
                status="failure",
            ),
        ],
    )
    error_status = LumberjackStatus(
        name="hooks",
        pid=4242,
        started_at="2026-05-09T10:00:00",
        status="error",
        interval=60,
        chops=["fast_lint"],
        last_cycle="2026-05-09T10:05:00",
        cycles_run=5,
        errors_encountered=3,
        uptime_seconds=300,
    )
    metrics = LumberjackMetrics(
        cycles_run=5, chops_executed=5, total_updates=2, errors_encountered=3
    )
    log_tail = "ERROR: hooks crashed at cycle 5"
    return axe_collected_data(
        lumberjack_names=["hooks"],
        lumberjack_statuses={"hooks": error_status},
        lumberjack_metrics={"hooks": metrics},
        lumberjack_log_tails={"hooks": log_tail},
        lumberjack_chop_names={"hooks": ["fast_lint"]},
        chop_snapshots={("hooks", "fast_lint"): failed_chop},
        lumberjack_snapshots={
            "hooks": LumberjackSnapshot(
                name="hooks",
                status=error_status,
                metrics=metrics,
                log_tail=log_tail,
                chops=[failed_chop],
            ),
        },
    )


def axe_running_chop_data() -> AxeCollectedData:
    """Build an in-flight manual chop run streaming its output."""
    # Naive ISO timestamps make _format_relative_time / _format_runtime
    # return the deterministic "unknown" fallback (they require tz-aware
    # input), so the rendered "Elapsed"/"When" cells stay stable across runs.
    live_entry = ChopRunEntry(
        run_id="20260509T100200_000000",
        lumberjack_name="hooks",
        chop_name="slow_typecheck",
        started_at="2026-05-09T10:02:00",
        finished_at=None,
        duration_ms=0,
        status="running",  # type: ignore[arg-type]
        exit_code=None,
        pid=98765,
        output_bytes=42,
        output_log="20260509T100200_000000.log",
        source="manual",  # type: ignore[arg-type]
    )
    live_run = ChopRunSnapshot(
        entry=live_entry,
        output_tail="checking module foo...\nchecking module bar...\n",
    )
    hooks_slow = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="slow_typecheck",
        description="slow typecheck",
        runs=[live_run],
    )
    chop_snapshots = {("hooks", "slow_typecheck"): hooks_slow}
    hooks_status = make_lumberjack_status("hooks", chops=["slow_typecheck"])
    metrics = LumberjackMetrics(
        cycles_run=12, chops_executed=24, total_updates=12, errors_encountered=0
    )
    lumberjack_snapshots = {
        "hooks": LumberjackSnapshot(
            name="hooks",
            status=hooks_status,
            metrics=metrics,
            log_tail="",
            chops=[hooks_slow],
        ),
    }
    return axe_collected_data(
        lumberjack_names=["hooks"],
        lumberjack_statuses={"hooks": hooks_status},
        lumberjack_metrics={"hooks": metrics},
        lumberjack_log_tails={"hooks": ""},
        lumberjack_chop_names={"hooks": ["slow_typecheck"]},
        chop_snapshots=chop_snapshots,
        lumberjack_snapshots=lumberjack_snapshots,
    )


def axe_chop_overrun_data() -> AxeCollectedData:
    """One lumberjack with an over chop, an intermittent chop, and a healthy one.

    Pins the sidebar chop chips (bold amber ``over``, dim amber
    ``intermittent``, none for the healthy chop), the lumberjack roll-up
    chip, the overview table's PACE column, and the advisory line below it —
    every surface the tab_indicator phase touches, in one screenshot.
    """
    over_chop = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="mentor_sweep",
        description="Sweep open mentor threads for stale review requests",
        runs=[
            make_chop_run(
                "hooks",
                "mentor_sweep",
                run_id="20260509T100400_000000",
                status="success",
            ),
        ],
        interval_seconds=60,
        interval_source="runtime",
        overrun=ChopOverrun(
            level="over",
            sampled_runs=5,
            over_runs=3,
            worst_ratio=4.0,
            worst_blocking_ms=240_000,
            latest_ratio=4.0,
            run_ratios=(4.0,),
        ),
    )
    intermittent_chop = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="bead_triage",
        description="Triage newly opened task beads",
        runs=[
            make_chop_run(
                "hooks",
                "bead_triage",
                run_id="20260509T100300_000000",
                status="success",
            ),
        ],
        interval_seconds=60,
        interval_source="runtime",
        overrun=ChopOverrun(
            level="intermittent",
            sampled_runs=8,
            over_runs=2,
            worst_ratio=1.2,
            worst_blocking_ms=72_000,
            latest_ratio=0.4,
            run_ratios=(0.4,),
        ),
    )
    healthy_chop = ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fix_hooks",
        description="Apply automatic hook fixes",
        runs=[
            make_chop_run(
                "hooks",
                "fix_hooks",
                run_id="20260509T100200_000000",
                status="success",
            ),
        ],
        interval_seconds=60,
        interval_source="runtime",
        overrun=ChopOverrun(
            level="none",
            sampled_runs=6,
            over_runs=0,
            worst_ratio=0.1,
            worst_blocking_ms=3_100,
            latest_ratio=0.1,
            run_ratios=(0.1,),
        ),
    )
    chop_snapshots = {
        ("hooks", "mentor_sweep"): over_chop,
        ("hooks", "bead_triage"): intermittent_chop,
        ("hooks", "fix_hooks"): healthy_chop,
    }
    hooks_status = make_lumberjack_status(
        "hooks", chops=["fix_hooks", "bead_triage", "mentor_sweep"]
    )
    metrics = LumberjackMetrics(
        cycles_run=31, chops_executed=93, total_updates=31, errors_encountered=0
    )
    return axe_collected_data(
        lumberjack_names=["hooks"],
        lumberjack_statuses={"hooks": hooks_status},
        lumberjack_metrics={"hooks": metrics},
        lumberjack_log_tails={"hooks": ""},
        lumberjack_chop_names={"hooks": ["fix_hooks", "bead_triage", "mentor_sweep"]},
        chop_snapshots=chop_snapshots,
        lumberjack_snapshots={
            "hooks": LumberjackSnapshot(
                name="hooks",
                status=hooks_status,
                metrics=metrics,
                log_tail="",
                chops=[healthy_chop, intermittent_chop, over_chop],
                overrun_chop_count=1,
                intermittent_chop_count=1,
            ),
        },
    )
