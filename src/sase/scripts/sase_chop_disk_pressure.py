#!/usr/bin/env python3
"""React to disk pressure from the hourly housekeeping lane."""

from __future__ import annotations

import shutil

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.disk_footprint import (
    collect_disk_footprint,
    format_bytes,
    run_disk_reap,
)
from sase.core.disk_pressure import classify_disk_pressure
from sase.core.paths import sase_home
from sase.notifications.senders import notify_workflow_complete


@builtin_chop("disk_pressure")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    usage = shutil.disk_usage(sase_home())
    observation = {
        "label": "sase_home",
        "role": "primary",
        "path": str(sase_home()),
        "measurement_path": str(sase_home()),
        "total_bytes": int(usage.total),
        "used_bytes": int(usage.used),
        "free_bytes": int(usage.free),
    }
    initial_pressure = classify_disk_pressure((observation,), top_owner_limit=0)
    pressure_row = initial_pressure["observations"][0]
    free_percent = float(pressure_row["free_percent"])
    if not initial_pressure["pressure_active"]:
        return runtime.emit_summary(
            {
                "status": 0,
                "free_percent_x100": int(free_percent * 100),
                "effective_warn_free_bytes": int(
                    initial_pressure["effective_warn_free_bytes"]
                ),
                "top_owners": 0,
                "steps": 0,
                "changed": 0,
            },
            reason="space_ok",
        )

    report = collect_disk_footprint()
    pressure = classify_disk_pressure(
        (observation,),
        owner_rows=(row.to_json_dict() for row in report.rows),
    )
    top_rows = tuple(pressure["top_owners"])
    for row in top_rows:
        runtime.log.info(
            "disk_pressure owner: "
            f"{row['owner']} {format_bytes(int(row['size_bytes']))} {row['path']}"
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
                    f"{row['owner']} {format_bytes(int(row['size_bytes']))}"
                    for row in top_rows
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
        filesystem_available_bytes=int(usage.free),
        managed_tmp_pressure_min_available_bytes=int(
            pressure["effective_warn_free_bytes"]
        ),
        managed_tmp_pressure_recovery_available_bytes=int(
            pressure["effective_warn_free_bytes"]
        ),
    )
    changed = int(result.changed)
    return runtime.emit_summary(
        {
            "status": 1,
            "free_percent_x100": int(free_percent * 100),
            "effective_warn_free_bytes": int(pressure["effective_warn_free_bytes"]),
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
