"""Shared fixtures for the axe dashboard test suite."""

from __future__ import annotations

from sase.ace.tui.actions.axe_display._data import ChopRunSnapshot, ChopSnapshot
from sase.axe.state import ChopRunEntry


def _entry(
    run_id: str,
    *,
    status: str = "success",
    duration_ms: int = 250,
    output_log: str = "run.log",
    started_at: str = "2026-05-11T12:34:56",
    finished_at: str | None = "2026-05-11T12:34:57",
    exit_code: int | None = None,
    pid: int | None = None,
    source: str = "scheduled",
) -> ChopRunEntry:
    return ChopRunEntry(
        run_id=run_id,
        lumberjack_name="hooks",
        chop_name="fast",
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        status=status,  # type: ignore[arg-type]
        exit_code=exit_code
        if exit_code is not None
        else (0 if status == "success" else 1),
        output_log=output_log,
        pid=pid,
        source=source,  # type: ignore[arg-type]
    )


def _snapshot_with_runs(*runs: ChopRunSnapshot) -> ChopSnapshot:
    return ChopSnapshot(
        lumberjack_name="hooks",
        chop_name="fast",
        description="fast description",
        runs=list(runs),
    )
