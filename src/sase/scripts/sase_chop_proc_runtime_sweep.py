#!/usr/bin/env python3
"""Sweep historical rowless proc runtime directories from housekeeping."""

from __future__ import annotations

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.procs.runtime import sweep_orphan_proc_runtime_dirs


@builtin_chop("proc_runtime_sweep")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    result = sweep_orphan_proc_runtime_dirs(apply=True)
    if result.removed:
        runtime.log(result.describe(), "cyan")
    return runtime.emit_summary(
        {
            "scanned": result.scanned,
            "selected": result.selected,
            "removed": result.removed,
            "skipped": result.skipped,
            "errors": result.errors,
            "reclaimable_bytes": result.reclaimable_bytes,
            "reclaimed_bytes": result.reclaimed_bytes,
            "capped": int(result.capped),
        },
        reason="nothing_eligible" if not result.selected else None,
    )


def main() -> None:
    run_builtin_chop("proc_runtime_sweep")


if __name__ == "__main__":
    main()
