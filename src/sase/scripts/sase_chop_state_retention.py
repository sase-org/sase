#!/usr/bin/env python3
"""Apply ToolRun log retention on a schedule from housekeeping.

Runs on the hourly ``housekeeping`` lumberjack. It calls the existing
``tool_run_retention`` owner at most once per configured interval, whether or
not the filesystem is under disk pressure, then removes emptied run
directories. ``clutter_reapers`` adds further classes to this same chop.
"""

from __future__ import annotations

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.state_retention import (
    StateRetentionOutcome,
    outcome_summary_fields,
    run_state_retention,
)


@builtin_chop("state_retention")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    outcome = run_state_retention()
    if outcome.owner_step is not None:
        runtime.log(outcome.owner_step.summary, "cyan")
    if outcome.owner_skipped:
        runtime.log(
            "state_retention: tool-run owner skipped; interval not elapsed",
            "cyan",
        )
    if outcome.empty_dirs.removed:
        runtime.log(
            f"state_retention: removed {outcome.empty_dirs.removed} empty run dir(s)",
            "cyan",
        )
    for error in outcome.errors[:5]:
        runtime.log.warning(f"state_retention: {error}")
    reason = _reason_for(outcome)
    result = runtime.emit_summary(outcome_summary_fields(outcome), reason=reason)
    if outcome.errors:
        result.status = "check_error"
    return result


def _reason_for(outcome: StateRetentionOutcome) -> str | None:
    if outcome.errors:
        return "retention_failed"
    if outcome.owner_skipped and not outcome.empty_dirs.removed:
        return "interval_gated"
    changed = bool(
        outcome.owner_applied
        and outcome.owner_step is not None
        and outcome.owner_step.changed
    )
    if not changed and not outcome.empty_dirs.removed:
        return "nothing_eligible"
    return None


def main() -> None:
    run_builtin_chop("state_retention")


if __name__ == "__main__":
    main()
