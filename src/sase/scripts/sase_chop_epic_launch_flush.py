#!/usr/bin/env python3
"""Flush planner completions orphaned by missing epic-launch settlement."""

from sase.bead.epic_launch_handoff import flush_orphaned_deferrals
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder


@builtin_chop("epic_launch_flush")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    result = flush_orphaned_deferrals()
    actions = result.flushed + result.settled_reaped
    if actions:
        runtime.log(
            "Epic completion handoff cleanup "
            f"flushed={result.flushed} settled_reaped={result.settled_reaped}",
            "cyan",
        )
    if result.errors:
        runtime.log.warning(
            f"Epic completion handoff cleanup encountered {result.errors} error(s)"
        )
    reason = None
    if not actions:
        reason = "errors" if result.errors else "nothing_due"
    return runtime.emit_summary(
        {
            "pending": result.pending_scanned,
            "active": result.active,
            "young": result.young,
            "flushed": result.flushed,
            "settled_reaped": result.settled_reaped,
            "errors": result.errors,
        },
        reason=reason,
    )


def main() -> None:
    run_builtin_chop("epic_launch_flush")


if __name__ == "__main__":
    main()
