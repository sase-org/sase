#!/usr/bin/env python3
"""React to disk pressure from the hourly housekeeping lane."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from typing import Any
from uuid import uuid4

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
from sase.core.disk_pressure_recovery import (
    INVENTORY_TIMEOUT_SECONDS,
    PRESSURE_NOTICE_SENDER,
    build_escalation_notes,
    build_pressure_notes,
    collect_inventory_fail_open,
    end_all_episodes,
    end_inactive_episodes,
    escalation_plus_one_note,
    filesystem_id,
    pressure_escalation_key,
    pressure_notice_key,
    pressure_plus_one_note,
    start_or_continue_episode,
)
from sase.core.paths import managed_tmpdir_root, sase_home
from sase.core.time import get_timezone
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import upsert_notification


@builtin_chop("disk_pressure")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    home = sase_home()
    targets = (
        {"label": "managed_tmp", "role": "owner", "path": str(managed_tmpdir_root())},
        {"label": "sase_home", "role": "owner", "path": str(home)},
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
        end_all_episodes(home)
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
    inventory = collect_inventory_fail_open(
        collect_disk_footprint,
        timeout_seconds=INVENTORY_TIMEOUT_SECONDS,
    )
    report = inventory.report
    pressure = initial_pressure
    if report is not None:
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
    missed_target = (
        available_after_bytes is not None
        and available_after_bytes < recovery_target_bytes
    )
    fs_id = filesystem_id(pressure_row)
    episode_id = start_or_continue_episode(home, fs_id)
    pressured = {
        filesystem_id(row)
        for row in pressure["observations"]
        if str(row.get("status") or "OK") != "OK"
    }
    end_inactive_episodes(home, pressured)
    notification_failed = _publish_notices(
        runtime,
        pressure_row=pressure_row,
        free_percent=free_percent,
        reclaimed_bytes=reclaimed_bytes,
        available_after_bytes=available_after_bytes,
        recovery_target_bytes=recovery_target_bytes,
        top_rows=top_rows,
        report=report,
        unavailable_reason=inventory.unavailable_reason,
        changed_owners=changed_owners,
        failed_owners=failed_owners,
        blocked_owners=blocked_owners,
        incomplete_owners=incomplete_owners,
        owners=owners,
        fs_id=fs_id,
        episode_id=episode_id,
        missed_target=missed_target,
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
    elif missed_target:
        check_error = True
        reason = "recovery_missed"
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


def _publish_notices(
    runtime: BuiltinChopRuntime,
    *,
    pressure_row: dict[str, Any],
    free_percent: float,
    reclaimed_bytes: int,
    available_after_bytes: int | None,
    recovery_target_bytes: int,
    top_rows: tuple[dict[str, Any], ...],
    report: Any,
    unavailable_reason: str | None,
    changed_owners: tuple[str, ...],
    failed_owners: tuple[str, ...],
    blocked_owners: tuple[str, ...],
    incomplete_owners: tuple[str, ...],
    owners: tuple[dict[str, Any], ...],
    fs_id: str,
    episode_id: str,
    missed_target: bool,
) -> int:
    notification_failed = 0
    details = build_pressure_notes(
        pressure_row=pressure_row,
        free_percent=free_percent,
        reclaimed_bytes=reclaimed_bytes,
        available_after_bytes=available_after_bytes,
        recovery_target_bytes=recovery_target_bytes,
        top_rows=top_rows,
        report=report,
        unavailable_reason=unavailable_reason,
        changed_owners=changed_owners,
        failed_owners=failed_owners,
        blocked_owners=blocked_owners,
        incomplete_owners=incomplete_owners,
    )
    if not _upsert_notice(
        runtime,
        notes=details,
        dedup_key=pressure_notice_key(fs_id, episode_id),
        plus_one_note=pressure_plus_one_note(
            free_bytes=int(pressure_row["free_bytes"]),
            reclaimed_bytes=reclaimed_bytes,
        ),
        tags=["disk", "housekeeping"],
    ):
        notification_failed = 1
    if missed_target and available_after_bytes is not None:
        escalation = build_escalation_notes(
            pressure_row=pressure_row,
            reclaimed_bytes=reclaimed_bytes,
            available_after_bytes=available_after_bytes,
            recovery_target_bytes=recovery_target_bytes,
            owners=owners,
            top_rows=top_rows,
            report=report,
        )
        if not _upsert_notice(
            runtime,
            notes=escalation,
            dedup_key=pressure_escalation_key(fs_id, episode_id),
            plus_one_note=escalation_plus_one_note(
                available_after_bytes=available_after_bytes,
                recovery_target_bytes=recovery_target_bytes,
            ),
            tags=["disk", "housekeeping", "escalation"],
        ):
            notification_failed = 1
    return notification_failed


def _upsert_notice(
    runtime: BuiltinChopRuntime,
    *,
    notes: list[str],
    dedup_key: str,
    plus_one_note: str,
    tags: list[str],
) -> bool:
    timestamp = datetime.now(get_timezone()).isoformat()
    try:
        upsert_notification(
            Notification(
                id=str(uuid4()),
                timestamp=timestamp,
                sender=PRESSURE_NOTICE_SENDER,
                notes=notes,
                tags=normalize_notification_tags(tags),
                dedup_key=dedup_key,
            ),
            plus_one_note=plus_one_note,
            plus_one_timestamp=timestamp,
        )
    except Exception as exc:  # noqa: BLE001 - reclaim already ran; report notify loss.
        runtime.log.warning(
            f"disk_pressure notification failed: {type(exc).__name__}: "
            f"{_bounded_error(exc)}"
        )
        return False
    return True


def _statvfs_available_bytes(path: str) -> int:
    """Measure available bytes without rescanning the disk footprint."""

    stats = os.statvfs(path)
    return int(stats.f_bavail * stats.f_frsize)


def _owner_list(owners: tuple[str, ...]) -> str:
    return ",".join(owners) if owners else "none"


def _bounded_error(exc: Exception) -> str:
    detail = " ".join(str(exc).split())
    return detail[:300] + ("…" if len(detail) > 300 else "")


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
