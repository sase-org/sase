#!/usr/bin/env python3
"""Managed SASE temp root reaping chop script.

Runs on the hourly ``housekeeping`` lumberjack rather than on an interactive
path: the first pass over a long-neglected root walks tens of thousands of
entries, which must never sit in front of a TUI startup or a CLI command.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core import managed_tmp_reaper as _managed_tmp_reaper
from sase.core.disk_pressure import filesystem_pressure_policy
from sase.core.managed_tmp_reaper import reap_managed_tmpdir
from sase.core.managed_tmp_roots import (
    effective_managed_tmp_roots as _effective_managed_tmp_roots,
)
from sase.core.paths import sase_home

effective_managed_tmp_roots = _effective_managed_tmp_roots


@builtin_chop("managed_tmp_reap")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    effective_root = _managed_tmp_reaper.managed_tmpdir_root()
    roots = effective_managed_tmp_roots(
        effective_root=effective_root, sase_home=sase_home()
    )
    results = [_reap_one_root(root) for root in roots]
    for result in results:
        # Always name each scanned root: a `nothing_stale` result over the
        # wrong root is exactly the sase-15q failure mode.
        runtime.log(result.describe(), "cyan")
    runtime.log.info(_managed_tmp_roots_info([result.root for result in results]))
    combined = _combine_results(results)
    # A mismatch between the effective root and the default root is now
    # harmless: every registered root is reaped, so there is no warning.
    return runtime.emit_summary(
        combined,
        reason="nothing_stale" if not combined["removed"] else None,
    )


def _reap_one_root(root: Path) -> Any:
    policy = filesystem_pressure_policy(
        label="managed_tmp",
        role="owner",
        path=root,
    )
    return reap_managed_tmpdir(
        root=root,
        filesystem_available_bytes=policy.free_bytes,
        pressure_min_available_bytes=policy.warn_free_bytes,
        pressure_recovery_available_bytes=policy.warn_free_bytes,
    )


def _combine_results(results: list[Any]) -> dict[str, Any]:
    """Sum per-root reaper results into one structured summary."""
    selected_by_subdir: dict[str, int] = {}
    removed_by_subdir: dict[str, int] = {}
    for result in results:
        for name, count in result.selected_by_subdir.items():
            selected_by_subdir[name] = selected_by_subdir.get(name, 0) + count
        for name, count in result.removed_by_subdir.items():
            removed_by_subdir[name] = removed_by_subdir.get(name, 0) + count
    triggers = [result.pressure_trigger for result in results]
    triggers = [trigger for trigger in triggers if trigger]
    first_triggered = next(
        (result for result in results if result.pressure_trigger), None
    )
    pressure_available_bytes = (
        first_triggered.pressure_available_bytes
        if first_triggered is not None and first_triggered.pressure_trigger
        else None
    )
    pressure_recovery_available_bytes = (
        first_triggered.pressure_recovery_available_bytes
        if first_triggered is not None and first_triggered.pressure_trigger
        else None
    )
    min_age_seconds = (
        int(first_triggered.pressure_effective_min_age_seconds)
        if first_triggered is not None
        and first_triggered.pressure_trigger
        and first_triggered.pressure_effective_min_age_seconds is not None
        else None
    )
    return {
        "roots_scanned": len(results),
        "scanned": sum(result.scanned for result in results),
        "selected": sum(result.selected for result in results),
        "removed": sum(result.removed for result in results),
        "selected_bytes": sum(result.selected_bytes for result in results),
        "removed_bytes": sum(result.removed_bytes for result in results),
        "subdirs": len(removed_by_subdir),
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
        "pressure_available_bytes": pressure_available_bytes,
        "pressure_recovery_available_bytes": pressure_recovery_available_bytes,
        "pressure_min_age_seconds": min_age_seconds,
        "deindexed": sum(result.deindexed for result in results),
        "capped": int(any(result.capped for result in results)),
        "skipped": sum(result.skipped for result in results),
        "failed": sum(result.failed for result in results),
        "incomplete_observations": sum(
            result.incomplete_observations for result in results
        ),
    }


def _managed_tmp_roots_info(roots: list[Path]) -> str:
    """Describe the roots one reaper pass scanned, for the run log."""
    noun = "root" if len(roots) == 1 else "roots"
    listed = ", ".join(str(root) for root in roots)
    return f"managed tmp reaper scans {len(roots)} {noun}: {listed}"


def main() -> None:
    run_builtin_chop("managed_tmp_reap")


if __name__ == "__main__":
    main()
