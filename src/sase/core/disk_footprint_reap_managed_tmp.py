"""Managed tmp owner step for ``sase disk reap``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.core import managed_tmp_reaper as _managed_tmp_reaper
from sase.core.disk_footprint_models import DiskReapStep
from sase.core.disk_pressure import filesystem_pressure_policy
from sase.core.managed_tmp_reaper import reap_managed_tmpdir
from sase.core.paths import managed_tmpdir_root as _paths_managed_tmpdir_root

managed_tmpdir_root = _paths_managed_tmpdir_root


def managed_tmp_reap_step(
    *,
    apply: bool,
    filesystem_available_bytes: int | None = None,
    pressure_min_available_bytes: int | None = None,
    pressure_recovery_available_bytes: int | None = None,
) -> DiskReapStep:
    try:
        return _managed_tmp_reap_step_impl(
            apply=apply,
            filesystem_available_bytes=filesystem_available_bytes,
            pressure_min_available_bytes=pressure_min_available_bytes,
            pressure_recovery_available_bytes=pressure_recovery_available_bytes,
        )
    except Exception as exc:  # noqa: BLE001 - one owner must not crash the group.
        return DiskReapStep(
            owner="managed_tmp_reaper",
            mode="error",
            summary=f"managed tmp cleanup failed: {type(exc).__name__}: {exc}",
            command=("sase", "disk", "reap", "--apply"),
            exit_code=1,
            owner_error=f"{type(exc).__name__}: {exc}",
            byte_accounting_complete=False,
        )


def _managed_tmp_reap_step_impl(
    *,
    apply: bool,
    filesystem_available_bytes: int | None = None,
    pressure_min_available_bytes: int | None = None,
    pressure_recovery_available_bytes: int | None = None,
) -> DiskReapStep:
    root = _current_managed_tmpdir_root()
    if (
        filesystem_available_bytes is None
        or pressure_min_available_bytes is None
        or pressure_recovery_available_bytes is None
    ):
        policy = filesystem_pressure_policy(
            label="managed_tmp",
            role="owner",
            path=root,
        )
        if filesystem_available_bytes is None:
            filesystem_available_bytes = policy.free_bytes
        if pressure_min_available_bytes is None:
            pressure_min_available_bytes = policy.warn_free_bytes
        if pressure_recovery_available_bytes is None:
            pressure_recovery_available_bytes = policy.warn_free_bytes
    result = reap_managed_tmpdir(
        root=root,
        apply=apply,
        filesystem_available_bytes=filesystem_available_bytes,
        pressure_min_available_bytes=pressure_min_available_bytes,
        pressure_recovery_available_bytes=pressure_recovery_available_bytes,
    )
    details = _managed_tmp_details(result)
    return DiskReapStep(
        owner="managed_tmp_reaper",
        mode="apply" if apply else "dry_run",
        summary=result.describe(),
        reclaimed_bytes=result.removed_bytes if apply else result.selected_bytes,
        changed=apply and bool(result.removed),
        exit_code=1 if result.failed else None,
        owner_error=(
            f"managed tmp cleanup reported {result.failed} failure(s)"
            if result.failed
            else None
        ),
        required_observation_unavailable=bool(result.incomplete_observations),
        incomplete_reason=(
            f"{result.incomplete_observations} required observation(s) incomplete"
            if result.incomplete_observations
            else None
        ),
        byte_accounting_complete=not bool(result.incomplete_observations),
        protective_skip=(
            "; ".join(str(reason) for reason in result.skip_reasons)
            if result.skip_reasons
            else None
        ),
        capped=bool(getattr(result, "capped", False)),
        details=details,
    )


def _current_managed_tmpdir_root() -> Path:
    if managed_tmpdir_root is not _paths_managed_tmpdir_root:
        return managed_tmpdir_root()
    return _managed_tmp_reaper.managed_tmpdir_root()


def _managed_tmp_details(result: Any) -> dict[str, Any]:
    return {
        "root": str(result.root),
        "scanned": result.scanned,
        "selected": result.selected,
        "removed": result.removed,
        "selected_bytes": result.selected_bytes,
        "removed_bytes": result.removed_bytes,
        "ordinary_selected": result.ordinary_selected,
        "ordinary_removed": result.ordinary_removed,
        "ordinary_reclaimable_bytes": result.ordinary_reclaimable_bytes,
        "ordinary_reclaimed_bytes": result.ordinary_reclaimed_bytes,
        "launch_selected": result.launch_selected,
        "launch_removed": result.launch_removed,
        "launch_reclaimable_bytes": result.launch_reclaimable_bytes,
        "launch_reclaimed_bytes": result.launch_reclaimed_bytes,
        "pressure_selected": result.pressure_selected,
        "pressure_removed": result.pressure_removed,
        "pressure_reclaimable_bytes": result.pressure_reclaimable_bytes,
        "pressure_reclaimed_bytes": result.pressure_reclaimed_bytes,
        "pressure_trigger": result.pressure_trigger,
        "pressure_root_size_bytes": result.pressure_root_size_bytes,
        "pressure_available_bytes": result.pressure_available_bytes,
        "pressure_recovery_available_bytes": result.pressure_recovery_available_bytes,
        "pressure_effective_min_age_seconds": (
            result.pressure_effective_min_age_seconds
        ),
        "skipped": result.skipped,
        "failed": result.failed,
        "incomplete_observations": result.incomplete_observations,
        "skip_reasons": list(result.skip_reasons),
        "removal_errors": list(result.removal_errors),
    }


__all__ = ["managed_tmp_reap_step"]
