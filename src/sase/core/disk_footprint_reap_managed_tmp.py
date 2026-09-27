"""Managed tmp owner step for ``sase disk reap``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.core import managed_tmp_reaper as _managed_tmp_reaper
from sase.core.disk_footprint_models import DiskReapStep
from sase.core.disk_pressure import filesystem_pressure_policy
from sase.core.managed_tmp_reaper import reap_managed_tmpdir
from sase.core.managed_tmp_roots import (
    effective_managed_tmp_roots as _effective_managed_tmp_roots,
)
from sase.core.paths import managed_tmpdir_root as _paths_managed_tmpdir_root
from sase.core.paths import sase_home as _paths_sase_home

managed_tmpdir_root = _paths_managed_tmpdir_root
effective_managed_tmp_roots = _effective_managed_tmp_roots


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
    roots = effective_managed_tmp_roots(
        effective_root=_current_managed_tmpdir_root(),
        sase_home=_paths_sase_home(),
    )
    results = [
        _reap_one_root(
            root,
            apply=apply,
            filesystem_available_bytes=filesystem_available_bytes,
            pressure_min_available_bytes=pressure_min_available_bytes,
            pressure_recovery_available_bytes=pressure_recovery_available_bytes,
        )
        for root in roots
    ]
    summaries = [result.describe() for result in results]
    failed = sum(result.failed for result in results)
    incomplete = sum(result.incomplete_observations for result in results)
    skip_reasons = [str(reason) for result in results for reason in result.skip_reasons]
    removed_bytes = sum(
        result.removed_bytes if apply else result.selected_bytes for result in results
    )
    changed = apply and any(bool(result.removed) for result in results)
    noun = "root" if len(results) == 1 else "roots"
    summary = f"{len(results)} {noun}: " + "; ".join(summaries)
    triggers = [
        result.pressure_trigger for result in results if result.pressure_trigger
    ]
    first_triggered = next(
        (result for result in results if result.pressure_trigger), None
    )
    # Without pressure the step still reports the observed filesystem free
    # space, matching the pre-registry single-root behavior.
    primary_pressure = (
        first_triggered
        if first_triggered is not None
        else (results[0] if results else None)
    )
    removal_errors = [
        str(message) for result in results for message in result.removal_errors
    ]
    return DiskReapStep(
        owner="managed_tmp_reaper",
        mode="apply" if apply else "dry_run",
        summary=summary,
        reclaimed_bytes=removed_bytes,
        changed=changed,
        exit_code=1 if failed else None,
        owner_error=(
            f"managed tmp cleanup reported {failed} failure(s)" if failed else None
        ),
        required_observation_unavailable=bool(incomplete),
        incomplete_reason=(
            f"{incomplete} required observation(s) incomplete" if incomplete else None
        ),
        byte_accounting_complete=not bool(incomplete),
        protective_skip="; ".join(skip_reasons) if skip_reasons else None,
        capped=any(bool(result.capped) for result in results),
        details={
            "roots": [str(result.root) for result in results],
            "roots_scanned": len(results),
            "scanned": sum(result.scanned for result in results),
            "selected": sum(result.selected for result in results),
            "removed": sum(result.removed for result in results),
            "selected_bytes": sum(result.selected_bytes for result in results),
            "removed_bytes": sum(result.removed_bytes for result in results),
            "ordinary_selected": sum(result.ordinary_selected for result in results),
            "ordinary_removed": sum(result.ordinary_removed for result in results),
            "ordinary_reclaimable_bytes": sum(
                result.ordinary_reclaimable_bytes for result in results
            ),
            "ordinary_reclaimed_bytes": sum(
                result.ordinary_reclaimed_bytes for result in results
            ),
            "launch_selected": sum(result.launch_selected for result in results),
            "launch_removed": sum(result.launch_removed for result in results),
            "launch_reclaimable_bytes": sum(
                result.launch_reclaimable_bytes for result in results
            ),
            "launch_reclaimed_bytes": sum(
                result.launch_reclaimed_bytes for result in results
            ),
            "pressure_selected": sum(result.pressure_selected for result in results),
            "pressure_removed": sum(result.pressure_removed for result in results),
            "pressure_reclaimable_bytes": sum(
                result.pressure_reclaimable_bytes for result in results
            ),
            "pressure_reclaimed_bytes": sum(
                result.pressure_reclaimed_bytes for result in results
            ),
            "pressure_trigger": "+".join(dict.fromkeys(triggers)) if triggers else None,
            "pressure_available_bytes": (
                primary_pressure.pressure_available_bytes
                if primary_pressure is not None
                else None
            ),
            "pressure_recovery_available_bytes": (
                primary_pressure.pressure_recovery_available_bytes
                if primary_pressure is not None
                else None
            ),
            "pressure_effective_min_age_seconds": (
                primary_pressure.pressure_effective_min_age_seconds
                if primary_pressure is not None
                else None
            ),
            "skipped": sum(result.skipped for result in results),
            "failed": failed,
            "incomplete_observations": incomplete,
            "skip_reasons": skip_reasons,
            "removal_errors": removal_errors,
            "per_root": [_managed_tmp_details(result) for result in results],
        },
    )


def _reap_one_root(
    root: Path,
    *,
    apply: bool,
    filesystem_available_bytes: int | None,
    pressure_min_available_bytes: int | None,
    pressure_recovery_available_bytes: int | None,
) -> Any:
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
    return reap_managed_tmpdir(
        root=root,
        apply=apply,
        filesystem_available_bytes=filesystem_available_bytes,
        pressure_min_available_bytes=pressure_min_available_bytes,
        pressure_recovery_available_bytes=pressure_recovery_available_bytes,
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
