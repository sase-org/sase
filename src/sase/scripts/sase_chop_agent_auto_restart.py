#!/usr/bin/env python3
"""Scheduler job: sweep update-skew recoveries and submit the healer proc.

Enumerates doorbells, recent failed rows, and stale/deferred/launched
ledger records, then submits ``sase agent auto-restart run -p -j`` as a
durable proc when work exists. Settles ``launched`` records from their
replacement's outcome and re-surfaces stale ``pending`` rows. When the
feature is off or paused, pending failures are re-surfaced loudly instead.
"""

from __future__ import annotations

from sase.agent.auto_restart.sweep import run_job_tick
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder


@builtin_chop("agent_auto_restart")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    tick = run_job_tick()
    summary = {
        "targets": tick.targets,
        "resurfaced": tick.resurfaced,
        "settled": tick.settled,
    }
    if tick.action == "submitted":
        runtime.log(f"submitted healer proc for {tick.targets} agent(s)", "cyan")
    elif tick.action not in ("idle",):
        runtime.log(f"auto-restart tick: {tick.action} ({tick.reason})", "cyan")
    return runtime.emit_summary(summary, reason=tick.reason)


def main() -> None:
    run_builtin_chop("agent_auto_restart")


if __name__ == "__main__":
    main()
