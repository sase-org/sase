#!/usr/bin/env python3
"""React to disk pressure from the hourly housekeeping lane."""

from __future__ import annotations

import shutil

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.config import get_disk_pressure_warn_free_percent
from sase.core.disk_footprint import (
    collect_disk_footprint,
    format_bytes,
    run_disk_reap,
)
from sase.core.paths import sase_home
from sase.notifications.senders import notify_workflow_complete


@builtin_chop("disk_pressure")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    usage = shutil.disk_usage(sase_home())
    free_percent = (usage.free / usage.total * 100.0) if usage.total else 0.0
    warn_percent = get_disk_pressure_warn_free_percent()
    if free_percent >= warn_percent:
        return runtime.emit_summary(
            {
                "status": 0,
                "free_percent_x100": int(free_percent * 100),
                "top_owners": 0,
                "steps": 0,
                "changed": 0,
            },
            reason="space_ok",
        )

    report = collect_disk_footprint()
    top_rows = tuple(row for row in report.rows[:5] if row.size_bytes > 0)
    for row in top_rows:
        runtime.log.info(
            "disk_pressure owner: "
            f"{row.owner} {format_bytes(row.size_bytes)} {row.path}"
        )
    if top_rows:
        notify_workflow_complete(
            "disk_pressure",
            None,
            False,
            [
                (
                    f"SASE disk pressure: {format_bytes(usage.free)} free "
                    f"({free_percent:.1f}%)"
                ),
                "Top owners: "
                + "; ".join(
                    f"{row.owner} {format_bytes(row.size_bytes)}" for row in top_rows
                ),
            ],
            tags=["disk", "housekeeping"],
        )

    # Artifact run deletion is intentionally excluded from unattended pressure
    # cleanup. `sase artifact prune-runs --apply` remains an explicit choice.
    result = run_disk_reap(
        apply=True,
        include_artifact_runs=False,
        include_workspace_compact=False,
    )
    changed = int(result.changed)
    return runtime.emit_summary(
        {
            "status": 1,
            "free_percent_x100": int(free_percent * 100),
            "top_owners": len(top_rows),
            "steps": len(result.steps),
            "changed": changed,
        },
        reason="pressure",
    )


def main() -> None:
    run_builtin_chop("disk_pressure")


if __name__ == "__main__":
    main()
