#!/usr/bin/env python3
"""Gate-shell reclaim chop script."""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.gate_shell.reclaim import GateShellReclaimSummary, reclaim_pending_gate_shells


def _reason_for(summary: GateShellReclaimSummary) -> str | None:
    if summary.errors:
        return "reclaim_errors"
    if not summary.scanned:
        return "no_pending_gate_shells"
    return None


@builtin_chop("gate_shell_reclaim")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    summary = reclaim_pending_gate_shells()
    for detail in summary.error_details:
        runtime.log.error(f"gate shell reclaim failed: {detail}")
    result = runtime.emit_summary(summary.to_dict(), reason=_reason_for(summary))
    if summary.errors:
        result.status = "check_error"
    return result


def main() -> None:
    run_builtin_chop("gate_shell_reclaim")


if __name__ == "__main__":
    main()
