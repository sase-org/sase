#!/usr/bin/env python3
"""Refresh subscription-usage windows inline on the ``usage`` routine.

Scheduled runs perform due-only inline refreshes; manual runs (the
Services-tab ``r`` key or ``sase axe job run``) perform explicit inline
refreshes, still subject to the cooldown and any ``Retry-After``. The
admitted batch probes in-process, so periodic collection creates no proc
rows. Collection is gated by ``llm_provider.usage_metrics.enabled``.
"""

from collections.abc import Mapping

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.llm_provider.usage.refresh import UsageRefreshReceipt


def _provider_statuses(receipt: UsageRefreshReceipt) -> dict[str, str]:
    """Map each receipt provider to its compact summary status."""
    outcomes = {
        str(item.get("provider") or ""): str(item.get("outcome") or "error")
        for item in receipt.inline_results
        if isinstance(item, Mapping)
    }
    statuses: dict[str, str] = {}
    for item in receipt.providers:
        if item.status in {"reserved", "joined"}:
            statuses[item.provider] = outcomes.get(item.provider, item.status)
        else:
            statuses[item.provider] = item.reason or item.status
    return statuses


def _summary_fields(receipt: UsageRefreshReceipt) -> dict[str, str | int | None]:
    """Build the chop summary fields from a receipt and inline results."""
    statuses = _provider_statuses(receipt)
    succeeded = sum(
        1 for status in statuses.values() if status in {"ok", "not_applicable"}
    )
    failed = sum(1 for status in statuses.values() if status == "error")
    deferred = sum(
        1
        for item in receipt.providers
        if item.status not in {"reserved", "joined", "error"}
    )
    fields: dict[str, str | int | None] = {
        "providers": len(receipt.providers),
        "succeeded": succeeded,
        "failed": failed,
        "deferred": deferred,
    }
    for provider in sorted(statuses):
        fields[provider] = statuses[provider]
    return fields


@builtin_chop("usage_refresh")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    from sase.llm_provider.usage.refresh import submit_usage_refresh

    manual = runtime.context.source != "scheduled"
    receipt = submit_usage_refresh(
        None,
        explicit=manual,
        origin="axe",
        execution="inline",
    )
    return runtime.emit_summary(
        _summary_fields(receipt),
        reason="nothing_due" if not receipt.started else None,
    )


def main() -> None:
    run_builtin_chop("usage_refresh")


if __name__ == "__main__":
    main()
