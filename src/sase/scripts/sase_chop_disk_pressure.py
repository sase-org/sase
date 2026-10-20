#!/usr/bin/env python3
"""React to disk pressure from the hourly housekeeping lane."""

from __future__ import annotations

import os
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
    # Artifact run cleanup is intentionally excluded from unattended pressure
    # cleanup; that owner is currently preview-only and apply fails closed.
    reap_result = run_disk_reap(
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
    cleanup = reap_result.cleanup_outcome
    owners = tuple(cleanup.get("owners", ()))
    changed_owners = tuple(
        str(owner["owner"]) for owner in owners if bool(owner.get("changed"))
    )
    failed_owners = tuple(
        str(owner["owner"]) for owner in owners if owner.get("status") == "failed"
    )
    blocked_owners = tuple(
        str(owner["owner"]) for owner in owners if owner.get("status") == "blocked"
    )
    incomplete_owners = tuple(
        str(owner["owner"]) for owner in owners if owner.get("status") == "incomplete"
    )
    reclaimed_bytes = int(cleanup.get("known_reclaimed_bytes", 0))
    recovery_target_bytes = int(pressure_row["warn_threshold_bytes_effective"])
    managed_tmp_recovery_target_bytes = int(
        managed_tmp_row["warn_threshold_bytes_effective"]
    )
    space_recheck_failed = 0
    available_after_bytes: int | None
    try:
        available_after_bytes = _statvfs_available_bytes(str(pressure_row["path"]))
    except Exception as exc:  # noqa: BLE001 - report an unverifiable recovery.
        available_after_bytes = None
        space_recheck_failed = 1
        runtime.log.warning(
            "disk_pressure free-space recheck failed: "
            f"{type(exc).__name__}: {_bounded_error(exc)}"
        )

    pressure_persists = (
        available_after_bytes is None or available_after_bytes < recovery_target_bytes
    )
    notification_failed = 0
    details = [
        (
            "SASE disk pressure: "
            f"{format_bytes(int(pressure_row['free_bytes']))} free "
            f"on {pressure_row['label']} ({free_percent:.1f}%)"
        ),
        "Top owners: "
        + (
            "; ".join(
                f"{row['owner']} {format_bytes(int(row['size_bytes']))}"
                for row in top_rows
            )
            if top_rows
            else "none reported"
        ),
        "Reap changed owners: " + _owner_list(changed_owners),
        "Reap failed owners: " + _owner_list(failed_owners),
        "Reap blocked/incomplete owners: "
        + _owner_list((*blocked_owners, *incomplete_owners)),
        f"Reclaimed: {format_bytes(reclaimed_bytes)}",
        "Available after: "
        + (
            format_bytes(available_after_bytes)
            if available_after_bytes is not None
            else "unknown"
        ),
        f"Recovery target: {format_bytes(recovery_target_bytes)}",
    ]
    unattributed_lead = _unattributed_lead_line(report, top_rows)
    if unattributed_lead is not None:
        details.insert(0, unattributed_lead)
    try:
        notify_workflow_complete(
            "disk_pressure",
            None,
            False,
            details,
            tags=["disk", "housekeeping"],
        )
    except Exception as exc:  # noqa: BLE001 - reclaim already ran; report notify loss.
        notification_failed = 1
        runtime.log.warning(
            f"disk_pressure notification failed: {type(exc).__name__}: "
            f"{_bounded_error(exc)}"
        )

    failed = len(failed_owners)
    blocked_or_incomplete = bool(blocked_owners or incomplete_owners)
    reason: str | None = None
    check_error = bool(failed or notification_failed or space_recheck_failed)
    if failed or notification_failed or space_recheck_failed:
        reason_parts = []
        if failed:
            reason_parts.append("cleanup_failed")
        if notification_failed:
            reason_parts.append("notify_failed")
        if space_recheck_failed:
            reason_parts.append("space_recheck_failed")
        reason = "+".join(reason_parts)
    elif pressure_persists and blocked_or_incomplete:
        check_error = True
        reason = "recovery_blocked"
    elif not changed_owners:
        reason = "nothing_eligible"

    result = runtime.emit_summary(
        {
            "status": 1,
            "free_percent_x100": int(free_percent * 100),
            "observations": len(observations),
            "effective_warn_free_bytes": int(
                pressure_row["warn_threshold_bytes_effective"]
            ),
            "top_owners": len(top_rows),
            "steps": len(reap_result.steps),
            "changed": len(changed_owners),
            "failed": failed,
            "blocked": len(blocked_owners),
            "incomplete": len(incomplete_owners),
            "reclaimed_bytes": reclaimed_bytes,
            "available_after_bytes": available_after_bytes,
            "recovery_target_bytes": recovery_target_bytes,
            "managed_tmp_recovery_target_bytes": managed_tmp_recovery_target_bytes,
            "notify_failed": notification_failed,
            "space_recheck_failed": space_recheck_failed,
            "changed_owners": _owner_list(changed_owners),
            "failed_owners": _owner_list(failed_owners),
            "blocked_owners": _owner_list(blocked_owners),
            "incomplete_owners": _owner_list(incomplete_owners),
        },
        reason=reason,
    )
    if check_error:
        result.status = "check_error"
    return result


def _statvfs_available_bytes(path: str) -> int:
    """Measure available bytes without rescanning the disk footprint."""

    stats = os.statvfs(path)
    return int(stats.f_bavail * stats.f_frsize)


def _owner_list(owners: tuple[str, ...]) -> str:
    return ",".join(owners) if owners else "none"


def _bounded_error(exc: Exception) -> str:
    detail = " ".join(str(exc).split())
    return detail[:300] + ("…" if len(detail) > 300 else "")


def _unattributed_lead_line(
    report: Any,
    top_rows: tuple[dict[str, Any], ...],
) -> str | None:
    """Lead the pressure notification with unattributed bytes when dominant.

    Returns a lead sentence when the inventory's ``unattributed`` row
    exceeds the largest attributed owner, otherwise ``None``.
    """

    unattributed_bytes = 0
    for row in report.rows:
        payload = row.to_json_dict() if hasattr(row, "to_json_dict") else row
        if payload.get("owner") != "unattributed":
            continue
        size = payload.get("exclusive_size_bytes")
        if size is None:
            size = payload.get("size_bytes") or 0
        unattributed_bytes = max(unattributed_bytes, int(size))
    if unattributed_bytes <= 0:
        return None
    largest_attributed = max(
        (
            int(row["size_bytes"])
            for row in top_rows
            if row.get("owner") != "unattributed"
        ),
        default=0,
    )
    if unattributed_bytes <= largest_attributed:
        return None
    return (
        f"Unattributed {format_bytes(unattributed_bytes)} on the SASE_HOME "
        "filesystem falls outside every inventoried owner; see sase disk list"
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
