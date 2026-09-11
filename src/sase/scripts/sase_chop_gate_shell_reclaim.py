#!/usr/bin/env python3
"""Gate-shell reclaim chop script."""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.gate_shell.reclaim import (
    GateHandoffReconcileSummary,
    GateShellReclaimSummary,
    reclaim_pending_gate_shells,
    reconcile_incomplete_gate_handoffs,
)


def _reason_for(
    summary: GateShellReclaimSummary, handoff: GateHandoffReconcileSummary
) -> str | None:
    if summary.errors or handoff.errors:
        return "reclaim_errors"
    if not summary.scanned and not handoff.scanned:
        return "no_pending_gate_shells"
    return None


@builtin_chop("gate_shell_reclaim")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    summary = reclaim_pending_gate_shells()
    handoff = reconcile_incomplete_gate_handoffs()
    for detail in summary.error_details:
        runtime.log.error(f"gate shell reclaim failed: {detail}")
    for detail in handoff.error_details:
        runtime.log.error(f"gate handoff reconcile failed: {detail}")
    payload = {**summary.to_dict(), **handoff.to_dict()}
    result = runtime.emit_summary(payload, reason=_reason_for(summary, handoff))
    if summary.errors or handoff.errors:
        result.status = "check_error"
    return result


def main() -> None:
    run_builtin_chop("gate_shell_reclaim")


if __name__ == "__main__":
    main()
