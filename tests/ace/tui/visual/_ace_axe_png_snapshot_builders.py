"""Reusable AXE data builders for PNG snapshot fixtures."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.axe_display._data import (
    AxeCollectedData,
    ChopRunSnapshot,
    ChopSnapshot,
    LumberjackSnapshot,
)
from sase.axe.state import ChopRunEntry, LumberjackMetrics, LumberjackStatus
from tests.ace.tui.visual._ace_png_snapshot_helpers import axe_collected_data


def make_lumberjack_status(
    name: str, status: str = "running", chops: list[str] | None = None
) -> LumberjackStatus:
    return LumberjackStatus(
        name=name,
        pid=4242,
        started_at="2026-05-09T10:00:00",
        status=status,  # type: ignore[arg-type]
        interval=60,
        chops=list(chops or []),
        last_cycle="2026-05-09T10:05:00",
        cycles_run=12,
        errors_encountered=0,
        uptime_seconds=300,
    )


def make_chop_run(
    lumberjack: str,
    chop: str,
    *,
    run_id: str,
    status: str,
    output_tail: str | None = None,
    result: dict[str, Any] | None = None,
    proposals: list[dict[str, Any]] | None = None,
    launches: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
    source: str = "scheduled",
    reason: str | None = None,
    error: str | None = None,
    traceback: str | None = None,
) -> ChopRunSnapshot:
    output_bytes = 64 if output_tail is None else len(output_tail.encode())
    tail = output_tail if output_tail is not None else f"{chop} {status} output\n"
    entry = ChopRunEntry(
        run_id=run_id,
        lumberjack_name=lumberjack,
        chop_name=chop,
        started_at="2026-05-09T10:00:00",
        finished_at="2026-05-09T10:00:01",
        duration_ms=1000,
        status=status,  # type: ignore[arg-type]
        exit_code=0 if status == "success" else 1,
        output_bytes=output_bytes,
        output_log=f"{run_id}.log",
        source=source,  # type: ignore[arg-type]
        result=result,
        proposals=list(proposals or []),
        launches=list(launches or []),
        dry_run=dry_run,
        reason=reason,
        error=error,
        traceback=traceback,
    )
    return ChopRunSnapshot(entry=entry, output_tail=tail)


def single_chop_data(chop: ChopSnapshot) -> AxeCollectedData:
    """Build a one-lumberjack AXE snapshot focused on a single chop run."""
    status = make_lumberjack_status(chop.lumberjack_name, chops=[chop.chop_name])
    metrics = LumberjackMetrics(
        cycles_run=9, chops_executed=18, total_updates=9, errors_encountered=0
    )
    return axe_collected_data(
        lumberjack_names=[chop.lumberjack_name],
        lumberjack_statuses={chop.lumberjack_name: status},
        lumberjack_metrics={chop.lumberjack_name: metrics},
        lumberjack_log_tails={chop.lumberjack_name: ""},
        lumberjack_chop_names={chop.lumberjack_name: [chop.chop_name]},
        chop_snapshots={(chop.lumberjack_name, chop.chop_name): chop},
        lumberjack_snapshots={
            chop.lumberjack_name: LumberjackSnapshot(
                name=chop.lumberjack_name,
                description="Runs report-oriented chops for visual review",
                description_summary="Runs report-oriented chops for visual review",
                description_body="",
                status=status,
                metrics=metrics,
                log_tail="",
                chops=[chop],
            ),
        },
    )
