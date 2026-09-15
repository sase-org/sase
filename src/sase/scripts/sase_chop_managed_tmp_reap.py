#!/usr/bin/env python3
"""Managed SASE temp root reaping chop script.

Runs on the hourly ``housekeeping`` lumberjack rather than on an interactive
path: the first pass over a long-neglected root walks tens of thousands of
entries, which must never sit in front of a TUI startup or a CLI command.
"""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.managed_tmp_reaper import reap_managed_tmpdir


@builtin_chop("managed_tmp_reap")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    result = reap_managed_tmpdir()
    pressure_available_bytes = (
        result.pressure_available_bytes if result.pressure_trigger else None
    )
    pressure_recovery_available_bytes = (
        result.pressure_recovery_available_bytes if result.pressure_trigger else None
    )
    pressure_min_age_seconds = (
        int(result.pressure_effective_min_age_seconds)
        if result.pressure_trigger
        and result.pressure_effective_min_age_seconds is not None
        else None
    )
    if result.removed:
        runtime.log(result.describe(), "cyan")
    return runtime.emit_summary(
        {
            "scanned": result.scanned,
            "selected": result.selected,
            "removed": result.removed,
            "selected_bytes": result.selected_bytes,
            "removed_bytes": result.removed_bytes,
            "subdirs": len(result.removed_by_subdir),
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
            "pressure_available_bytes": pressure_available_bytes,
            "pressure_recovery_available_bytes": pressure_recovery_available_bytes,
            "pressure_min_age_seconds": pressure_min_age_seconds,
            "deindexed": result.deindexed,
            "capped": int(result.capped),
            "skipped": result.skipped,
            "failed": result.failed,
            "incomplete_observations": result.incomplete_observations,
        },
        reason="nothing_stale" if not result.removed else None,
    )


def main() -> None:
    run_builtin_chop("managed_tmp_reap")


if __name__ == "__main__":
    main()
