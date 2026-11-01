#!/usr/bin/env python3
"""Recover finalized staged handoffs whose originating runner is gone."""

from sase.axe.staged_handoff_reconcile import reconcile_staged_handoffs
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder


@builtin_chop("staged_handoff_reconcile")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    if runtime.context.dry_run:
        return runtime.emit_summary({"adopted": 0}, reason="dry_run")
    summary = reconcile_staged_handoffs()
    for error in summary.errors:
        runtime.log.error(f"staged handoff reconciliation: {error}")
    for detail in summary.held_details:
        runtime.log.info(f"staged handoff remains pending: {detail}")
    reason = None
    if summary.busy:
        reason = "reconciliation_busy"
    elif not summary.adopted and not summary.delivered and not summary.errors:
        reason = "budget_exhausted" if summary.deferred else "no_pending_adoptions"
    result = runtime.emit_summary(
        {
            "scanned": summary.scanned,
            "inspected": summary.inspected,
            "adopted": summary.adopted,
            "delivered": summary.delivered,
            "already_adopted": summary.already_adopted,
            "held": summary.held,
            "deferred": summary.deferred,
            "errors": len(summary.errors),
        },
        reason=reason,
    )
    if summary.errors:
        result.status = "check_error"
    return result


def main() -> None:
    run_builtin_chop("staged_handoff_reconcile")


if __name__ == "__main__":
    main()
