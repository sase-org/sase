#!/usr/bin/env python3
"""React to disk pressure from the hourly housekeeping lane."""

from __future__ import annotations

import shutil
from typing import Any

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.disk_footprint import (
    collect_disk_footprint,
    format_bytes,
    run_disk_reap,
)
from sase.core.disk_pressure import (
    classify_disk_pressure,
    collect_filesystem_observations,
)
from sase.core.paths import managed_tmpdir_root, sase_home
from sase.notifications.senders import notify_workflow_complete


@builtin_chop("disk_pressure")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    targets = (
        {"label": "managed_tmp", "role": "owner", "path": str(managed_tmpdir_root())},
        {"label": "sase_home", "role": "owner", "path": str(sase_home())},
    )
    observations = collect_filesystem_observations(
        targets,
        disk_usage_fn=shutil.disk_usage,
    )
    initial_pressure = classify_disk_pressure(observations, top_owner_limit=0)
    pressure_row = _worst_pressure_row(initial_pressure["observations"])
    managed_tmp_row = _pressure_row_for_label(
        initial_pressure["observations"],
        "managed_tmp",
    )
    free_percent = float(pressure_row["free_percent"])
    if not initial_pressure["pressure_active"]:
        return runtime.emit_summary(
            {
                "status": 0,
                "free_percent_x100": int(free_percent * 100),
                "observations": len(observations),
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
        observations,
        owner_rows=(row.to_json_dict() for row in report.rows),
    )
    pressure_row = _worst_pressure_row(pressure["observations"])
    managed_tmp_row = _pressure_row_for_label(
        pressure["observations"],
        "managed_tmp",
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
                    "SASE disk pressure: "
                    f"{format_bytes(int(pressure_row['free_bytes']))} free "
                    f"on {pressure_row['label']} ({free_percent:.1f}%)"
                ),
                "Top owners: "
                + "; ".join(
                    f"{row['owner']} {format_bytes(int(row['size_bytes']))}"
                    for row in top_rows
                ),
            ],
            tags=["disk", "housekeeping"],
        )

    # Artifact run cleanup is intentionally excluded from unattended pressure
    # cleanup; that owner is currently preview-only and apply fails closed.
    result = run_disk_reap(
        apply=True,
        include_artifact_runs=False,
        include_workspace_compact=False,
        filesystem_available_bytes=int(managed_tmp_row["free_bytes"]),
        managed_tmp_pressure_min_available_bytes=int(
            managed_tmp_row["warn_threshold_bytes_effective"]
        ),
        managed_tmp_pressure_recovery_available_bytes=int(
            managed_tmp_row["warn_threshold_bytes_effective"]
        ),
    )
    changed = int(result.changed)
    failed = int(result.failed)
    return runtime.emit_summary(
        {
            "status": 1,
            "free_percent_x100": int(free_percent * 100),
            "observations": len(observations),
            "effective_warn_free_bytes": int(
                pressure_row["warn_threshold_bytes_effective"]
            ),
            "top_owners": len(top_rows),
            "steps": len(result.steps),
            "changed": changed,
            "failed": failed,
        },
        reason="pressure",
    )


def _worst_pressure_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    severity = {"ERROR": 2, "WARN": 1, "OK": 0}
    return max(
        rows,
        key=lambda row: (
            severity.get(str(row.get("status")), 0),
            -int(row.get("free_bytes") or 0),
        ),
    )


def _pressure_row_for_label(
    rows: list[dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    for row in rows:
        if row.get("label") == label:
            return row
    return _worst_pressure_row(rows)


def main() -> None:
    run_builtin_chop("disk_pressure")


if __name__ == "__main__":
    main()
