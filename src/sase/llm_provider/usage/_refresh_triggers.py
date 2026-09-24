"""Best-effort usage-refresh triggers and hot hints.

Store and probe helpers that tests patch on the public
:mod:`sase.llm_provider.usage.refresh` namespace are resolved with late imports
so the facade stays the single patch point.
"""

from __future__ import annotations

import logging
import time

from sase.llm_provider.usage._refresh_model import (
    HOT_HINT_TTL_SECONDS,
    USAGE_REFRESH_CONTEXT_ID,
)
from sase.llm_provider.usage.config import collection_skip_reason

log = logging.getLogger(__name__)


def _provider_has_probe_capability(provider: str) -> bool:
    """Return whether *provider* declares usage probe capability."""
    try:
        from sase.llm_provider.registry import get_llm_metadata_payload

        payload = get_llm_metadata_payload()
        providers = payload.get("providers")
        if not isinstance(providers, dict):
            return False
        metadata = providers.get(provider)
        if not isinstance(metadata, dict):
            return False
        capabilities = metadata.get("usage_capabilities")
        return isinstance(capabilities, dict) and capabilities.get("probe") is True
    except Exception:
        log.debug("usage probe-capability lookup failed for %r", provider)
        return False


def _mark_usage_refresh_due(
    provider: str,
    reason: str,
    *,
    due_at: float | None = None,
    now: float | None = None,
    context_id: str = USAGE_REFRESH_CONTEXT_ID,
) -> None:
    """Mark *provider* due once for *reason*. Never raises to callers."""
    from sase.llm_provider.usage.refresh import (
        mark_provider_usage_refresh_due,
        prepare_provider_usage_account_context,
    )

    try:
        context = prepare_provider_usage_account_context(provider, context_id, now=now)
        mark_provider_usage_refresh_due(
            provider,
            context.context_id,
            context.account_generation,
            reason,
            due_at=due_at,
            now=now,
        )
    except Exception:
        log.debug("could not mark usage refresh due for %r", provider, exc_info=True)


def mark_provider_usage_hot_hint(
    provider: str,
    *,
    context_id: str = USAGE_REFRESH_CONTEXT_ID,
    now: float | None = None,
) -> None:
    """Best-effort 15-minute hot hint for a provider in active use.

    Only writes when collection is enabled for *provider* and it declares
    probe capability. Never raises; a hint must not add latency or failure
    modes to launches.
    """
    from sase.llm_provider.usage.refresh import mark_provider_usage_hot

    try:
        if collection_skip_reason(provider) is not None:
            return
        if not _provider_has_probe_capability(provider):
            return
        current = time.time() if now is None else now
        mark_provider_usage_hot(
            provider, current + HOT_HINT_TTL_SECONDS, context_id=context_id, now=current
        )
    except Exception:
        log.debug("usage hot hint failed for %r", provider, exc_info=True)
    return None


def trigger_usage_refresh_after_limit_event(
    provider: str,
    *,
    expires_at: float | None = None,
    now: float | None = None,
) -> None:
    """Best-effort due mark after a usage-limit disable.

    Limit events only mark the provider due; the next routine tick picks it
    up subject to its polling floor. They never submit an explicit probe.
    A 15-minute hot hint keeps the provider on the hot cadence so the
    post-limit windows refresh promptly.
    """
    from sase.llm_provider.usage.refresh import mark_provider_usage_hot

    try:
        _mark_usage_refresh_due(provider, "limit_event", now=now)
        if expires_at is not None:
            _mark_usage_refresh_due(
                provider,
                "disable_expiry",
                due_at=expires_at,
                now=now,
            )
    except Exception:
        log.debug("usage-limit refresh trigger failed for %r", provider, exc_info=True)
    try:
        current = time.time() if now is None else now
        mark_provider_usage_hot(provider, current + HOT_HINT_TTL_SECONDS, now=current)
    except Exception:
        log.debug("usage-limit hot hint failed for %r", provider, exc_info=True)
    return None
