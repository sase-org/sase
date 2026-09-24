"""Submit/join orchestration for subscription-usage refresh.

Admission store helpers and probe metadata that tests patch on the public
:mod:`sase.llm_provider.usage.refresh` namespace are resolved with late imports
so the facade stays the single patch point.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from sase.llm_provider.usage._refresh_eligibility import _resolve_requested_providers
from sase.llm_provider.usage._refresh_execution import (
    _release_started,
    _run_inline_batch,
    _submit_started_proc,
)
from sase.llm_provider.usage._refresh_model import (
    INLINE_USAGE_OPERATION_PREFIX,
    USAGE_REFRESH_CONTEXT_ID,
    USAGE_REFRESH_EXECUTIONS,
    USAGE_REFRESH_LEASE_TTL_SECONDS,
    USAGE_REFRESH_ORIGINS,
    USAGE_REFRESH_RECEIPT_SCHEMA_VERSION,
    UsageRefreshReceipt,
    _UsageRefreshProviderResult,
)
from sase.llm_provider.usage.config import (
    collection_skip_reason,
    get_usage_metrics_settings,
)
from sase.llm_provider.usage.store import (
    PROVIDER_USAGE_REFRESH_DEFERRED,
    PROVIDER_USAGE_REFRESH_JOINED,
    PROVIDER_USAGE_REFRESH_RESERVED,
)

log = logging.getLogger(__name__)


def request_due_usage_refresh(
    *,
    origin: str = "axe",
    now: float | None = None,
    plugin_specs: Mapping[str, Mapping[str, Any]] | None = None,
    execution: str = "proc",
) -> UsageRefreshReceipt:
    """Submit coalesced refresh work for currently due eligible providers."""
    return submit_usage_refresh(
        None,
        explicit=False,
        origin=origin,
        now=now,
        plugin_specs=plugin_specs,
        execution=execution,
    )


def submit_usage_refresh(
    providers: Sequence[str] | None = None,
    *,
    explicit: bool = False,
    origin: str = "axe",
    now: float | None = None,
    plugin_specs: Mapping[str, Mapping[str, Any]] | None = None,
    execution: str = "proc",
) -> UsageRefreshReceipt:
    """Admit, join, or defer refresh work for *providers*.

    ``providers is None`` selects background-eligible providers that are due.
    An explicit filter inspects the named providers even when they are not
    background-eligible. Joining one in-flight provider never drops others.
    With ``execution="inline"`` the admitted batch runs in-process under a
    non-proc operation ID instead of submitting a proc; the per-provider
    runner results ride on the receipt's ``inline_results``.
    """
    origin = _normalize_origin(origin)
    execution = _normalize_execution(execution)
    from sase.procs import new_proc_id

    settings = get_usage_metrics_settings()
    if not settings.enabled:
        names = tuple(providers or ())
        return _disabled_receipt(names, origin, "config_disabled")

    requested = _resolve_requested_providers(providers)
    if not requested:
        return UsageRefreshReceipt(
            schema_version=USAGE_REFRESH_RECEIPT_SCHEMA_VERSION,
            origin=origin,
            operation_ids=(),
            providers=(),
        )

    results: list[_UsageRefreshProviderResult] = []
    started: list[_UsageRefreshProviderResult] = []
    if execution == "inline":
        operation_id = f"{INLINE_USAGE_OPERATION_PREFIX}{new_proc_id()}"
    else:
        operation_id = new_proc_id()
    specs = {str(name): dict(spec) for name, spec in (plugin_specs or {}).items()}
    cadence = settings.refresh_seconds

    for provider in requested:
        skip = collection_skip_reason(provider)
        if skip is not None:
            results.append(
                _UsageRefreshProviderResult(
                    provider=provider,
                    status="disabled",
                    reason=skip,
                    operation_id=None,
                )
            )
            continue
        try:
            result = _admit_one(
                provider,
                operation_id=operation_id,
                explicit=explicit,
                cadence_seconds=cadence,
                now=now,
            )
        except Exception:
            log.warning(
                "usage refresh admission failed for %r", provider, exc_info=True
            )
            results.append(
                _UsageRefreshProviderResult(
                    provider=provider,
                    status="error",
                    reason="admission_failed",
                    operation_id=None,
                )
            )
            continue
        results.append(result)
        if result.status == PROVIDER_USAGE_REFRESH_RESERVED:
            started.append(result)

    inline_results: tuple[Mapping[str, Any], ...] = ()
    if started:
        if execution == "inline":
            inline_results = tuple(
                _run_inline_batch(
                    started,
                    origin=origin,
                    plugin_specs=specs,
                    cadence_seconds=cadence,
                    now=now,
                )
            )
        else:
            try:
                _submit_started_proc(
                    started,
                    operation_id=operation_id,
                    origin=origin,
                    plugin_specs=specs,
                    cadence_seconds=cadence,
                )
            except Exception:
                log.warning("usage refresh proc submit failed", exc_info=True)
                _release_started(started, now=now)
                results = [
                    (
                        _UsageRefreshProviderResult(
                            provider=item.provider,
                            status="error",
                            reason="submit_failed",
                            operation_id=None,
                            context_id=item.context_id,
                            account_generation=item.account_generation,
                        )
                        if item.status == PROVIDER_USAGE_REFRESH_RESERVED
                        else item
                    )
                    for item in results
                ]
                started = []

    operation_ids = tuple(
        dict.fromkeys(
            item.operation_id
            for item in results
            if item.operation_id
            and item.status
            in {PROVIDER_USAGE_REFRESH_RESERVED, PROVIDER_USAGE_REFRESH_JOINED}
        )
    )
    return UsageRefreshReceipt(
        schema_version=USAGE_REFRESH_RECEIPT_SCHEMA_VERSION,
        origin=origin,
        operation_ids=operation_ids,
        providers=tuple(results),
        inline_results=inline_results,
    )


def _admit_one(
    provider: str,
    *,
    operation_id: str,
    explicit: bool,
    cadence_seconds: float,
    now: float | None,
    active_cadence_seconds: float | None = None,
    warn_percent: float | None = None,
) -> _UsageRefreshProviderResult:
    from sase.llm_provider.usage.refresh import (
        admit_provider_usage_refresh,
        evaluate_provider_usage_refresh_due,
        prepare_provider_usage_account_context,
        usage_cli_fingerprint,
        usage_probe_floor,
    )

    context = prepare_provider_usage_account_context(
        provider, USAGE_REFRESH_CONTEXT_ID, now=now
    )
    floor = usage_probe_floor(provider)
    fingerprint = usage_cli_fingerprint(provider)
    settings = get_usage_metrics_settings()
    active = (
        settings.active_refresh_seconds
        if active_cadence_seconds is None
        else active_cadence_seconds
    )
    warn = settings.warn_percent if warn_percent is None else warn_percent
    try:
        active = min(float(active), float(cadence_seconds))
    except (TypeError, ValueError):
        active = float(cadence_seconds)
    if not explicit:
        due = evaluate_provider_usage_refresh_due(
            provider,
            context.context_id,
            context.account_generation,
            cadence_seconds=cadence_seconds,
            explicit=False,
            adaptive=True,
            min_interval_seconds=floor,
            cli_fingerprint=fingerprint,
            active_cadence_seconds=active,
            warn_percent=warn,
            now=now,
        )
        if not due.due:
            return _UsageRefreshProviderResult(
                provider=provider,
                status=PROVIDER_USAGE_REFRESH_DEFERRED,
                reason=due.reason,
                operation_id=None,
                context_id=context.context_id,
                account_generation=context.account_generation,
                due_at=due.due_at,
            )
    admitted = admit_provider_usage_refresh(
        provider,
        context.context_id,
        context.account_generation,
        operation_id,
        USAGE_REFRESH_LEASE_TTL_SECONDS,
        cadence_seconds=cadence_seconds,
        explicit=explicit,
        adaptive=True,
        min_interval_seconds=floor,
        cli_fingerprint=fingerprint,
        active_cadence_seconds=active,
        warn_percent=warn,
        now=now,
    )
    reservation = admitted.reservation
    joined_operation = None if reservation is None else reservation.operation_id
    lease_id = None if reservation is None else reservation.lease_id
    status = admitted.status
    result_operation = joined_operation
    if status == PROVIDER_USAGE_REFRESH_DEFERRED:
        result_operation = None
    return _UsageRefreshProviderResult(
        provider=provider,
        status=status,
        reason=admitted.reason,
        operation_id=result_operation,
        lease_id=lease_id,
        context_id=context.context_id,
        account_generation=context.account_generation,
        due_at=admitted.due_at,
    )


def _disabled_receipt(
    providers: Sequence[str], origin: str, reason: str
) -> UsageRefreshReceipt:
    results = tuple(
        _UsageRefreshProviderResult(
            provider=name,
            status="disabled",
            reason=reason,
            operation_id=None,
        )
        for name in providers
    )
    return UsageRefreshReceipt(
        schema_version=USAGE_REFRESH_RECEIPT_SCHEMA_VERSION,
        origin=origin,
        operation_ids=(),
        providers=results,
    )


def _normalize_origin(origin: str) -> str:
    cleaned = origin.strip() or "axe"
    if cleaned not in USAGE_REFRESH_ORIGINS:
        return "axe"
    return cleaned


def _normalize_execution(execution: str) -> str:
    if execution in USAGE_REFRESH_EXECUTIONS:
        return execution
    raise ValueError(f"execution must be one of {USAGE_REFRESH_EXECUTIONS!r}")
