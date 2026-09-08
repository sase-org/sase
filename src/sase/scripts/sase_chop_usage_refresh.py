#!/usr/bin/env python3
"""Submit due subscription-usage refreshes through the shared durable service.

Runs on the five-minute ``checks`` lumberjack. Collection is gated by the
``provider_usage_metrics`` beta flag and ``llm_provider.usage_metrics.enabled``.
"""

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder


@builtin_chop("usage_refresh")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    from sase.llm_provider.usage.refresh import request_due_usage_refresh

    receipt = request_due_usage_refresh(origin="axe")
    started = sum(1 for item in receipt.providers if item.status == "reserved")
    joined = sum(1 for item in receipt.providers if item.status == "joined")
    deferred = sum(1 for item in receipt.providers if item.status == "deferred")
    disabled = sum(1 for item in receipt.providers if item.status == "disabled")
    return runtime.emit_summary(
        {
            "providers": len(receipt.providers),
            "started": started,
            "joined": joined,
            "deferred": deferred,
            "disabled": disabled,
            "operations": len(receipt.operation_ids),
        },
        reason="nothing_due" if not receipt.started else None,
    )


def main() -> None:
    run_builtin_chop("usage_refresh")


if __name__ == "__main__":
    main()
