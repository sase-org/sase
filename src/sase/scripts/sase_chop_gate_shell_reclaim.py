#!/usr/bin/env python3
"""Gate-shell reclaim chop script."""

import time

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.gate_shell.reclaim import (
    GateHandoffReconcileSummary,
    GateShellReclaimSummary,
    reclaim_pending_gate_shells,
    reconcile_incomplete_gate_handoffs,
)
from sase.gate_shell.store import load_gate_shell_snapshot

#: Keeps one pass's snapshot read plus both phases inside the chop's
#: ``timeout: "2m"`` (``src/sase/default_config.yml``), leaving room for one
#: in-flight gate's classify/persist plus the 5s follow-up lock wait.
_PASS_TIME_BUDGET_SECONDS = 75.0


def _reason_for(
    summary: GateShellReclaimSummary, handoff: GateHandoffReconcileSummary
) -> str | None:
    if summary.errors or handoff.errors:
        return "reclaim_errors"
    if not summary.scanned and not handoff.scanned:
        return "budget_exhausted" if handoff.deferred else "no_pending_gate_shells"
    return None


@builtin_chop("gate_shell_reclaim")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    started = time.monotonic()
    snapshot = load_gate_shell_snapshot()
    read_seconds = time.monotonic() - started
    runtime.log.info(
        "gate shell reclaim progress: snapshot read in "
        f"{read_seconds:.1f}s ({snapshot.record_count} record(s), "
        f"{len(snapshot.gate_shells)} gate shell(s))"
    )

    summary = reclaim_pending_gate_shells(snapshot=snapshot)
    runtime.log.info(
        "gate shell reclaim progress: reclaim phase done in "
        f"{time.monotonic() - started:.1f}s"
    )

    handoff = reconcile_incomplete_gate_handoffs(
        snapshot=snapshot,
        deadline=started + _PASS_TIME_BUDGET_SECONDS,
        snapshot_read_seconds=read_seconds,
        on_refresh=lambda gate, seconds: runtime.log.info(
            f"gate shell reclaim progress: snapshot refreshed for {gate} "
            f"in {seconds:.1f}s"
        ),
    )
    runtime.log.info(
        "gate shell reclaim progress: reconcile done in "
        f"{time.monotonic() - started:.1f}s"
    )

    if summary.accepted_unfinished:
        runtime.log.info(
            f"gate shell reclaim progress: {summary.accepted_unfinished} gate(s) "
            "have an accepted decision with execution still incomplete; deferring"
        )
    for detail in summary.error_details:
        runtime.log.error(f"gate shell reclaim failed: {detail}")
    for detail in handoff.error_details:
        runtime.log.error(f"gate handoff reconcile failed: {detail}")
    if handoff.deferred:
        runtime.log.warning(
            f"gate handoff reconcile deferred {handoff.deferred} gate(s) past its "
            "time budget; the next tick resumes from the saved cursor"
        )
    payload = {**summary.to_dict(), **handoff.to_dict()}
    result = runtime.emit_summary(payload, reason=_reason_for(summary, handoff))
    if summary.errors or handoff.errors:
        result.status = "check_error"
    return result


def main() -> None:
    run_builtin_chop("gate_shell_reclaim")


if __name__ == "__main__":
    main()
