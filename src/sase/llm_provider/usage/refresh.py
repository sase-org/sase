"""Shared durable subscription-usage refresh submit/join service.

Thin facade over the ``_refresh_*`` modules: shared constants and receipt
types live in :mod:`sase.llm_provider.usage._refresh_model`, background
eligibility in :mod:`sase.llm_provider.usage._refresh_eligibility`,
best-effort triggers in :mod:`sase.llm_provider.usage._refresh_triggers`,
submit/join orchestration in :mod:`sase.llm_provider.usage._refresh_submit`,
and proc/inline execution in
:mod:`sase.llm_provider.usage._refresh_execution`.
"""

from __future__ import annotations

from sase.llm_provider.usage._probe_meta import (
    usage_cli_fingerprint,
    usage_probe_floor,
    usage_probe_floors,
)
from sase.llm_provider.usage._refresh_eligibility import (
    eligible_usage_providers,
)
from sase.llm_provider.usage._refresh_execution import (
    wait_for_usage_refresh_operations,
)
from sase.llm_provider.usage._refresh_model import (
    HOT_HINT_TTL_SECONDS,
    INLINE_USAGE_OPERATION_PREFIX,
    MAX_CONCURRENT_USAGE_PROBES,
    USAGE_INLINE_WAIT_POLL_SECONDS,
    USAGE_REFRESH_BATCH_DEADLINE_SECONDS,
    USAGE_REFRESH_CONTEXT_ID,
    USAGE_REFRESH_EXECUTIONS,
    USAGE_REFRESH_LEASE_TTL_SECONDS,
    USAGE_REFRESH_OPERATION,
    USAGE_REFRESH_ORIGINS,
    USAGE_REFRESH_PROVIDER_DEADLINE_SECONDS,
    USAGE_REFRESH_RECEIPT_SCHEMA_VERSION,
    UsageRefreshProviderResult,
    UsageRefreshReceipt,
    is_inline_usage_operation,
)
from sase.llm_provider.usage._refresh_submit import (
    request_due_usage_refresh,
    submit_usage_refresh,
)
from sase.llm_provider.usage._refresh_triggers import (
    mark_provider_usage_hot_hint,
    trigger_usage_refresh_after_limit_event,
)
from sase.llm_provider.usage.store import (
    PROVIDER_USAGE_REFRESH_DEFERRED,
    PROVIDER_USAGE_REFRESH_JOINED,
    PROVIDER_USAGE_REFRESH_RESERVED,
    admit_provider_usage_refresh,
    evaluate_provider_usage_refresh_due,
    list_provider_usage_refresh_reservations,
    mark_provider_usage_hot,
    mark_provider_usage_refresh_due,
    prepare_provider_usage_account_context,
    record_provider_usage_refresh_attempt,
    release_provider_usage_refresh,
)

__all__ = [
    "HOT_HINT_TTL_SECONDS",
    "INLINE_USAGE_OPERATION_PREFIX",
    "MAX_CONCURRENT_USAGE_PROBES",
    "USAGE_INLINE_WAIT_POLL_SECONDS",
    "USAGE_REFRESH_BATCH_DEADLINE_SECONDS",
    "USAGE_REFRESH_CONTEXT_ID",
    "USAGE_REFRESH_EXECUTIONS",
    "USAGE_REFRESH_LEASE_TTL_SECONDS",
    "USAGE_REFRESH_OPERATION",
    "USAGE_REFRESH_ORIGINS",
    "USAGE_REFRESH_PROVIDER_DEADLINE_SECONDS",
    "USAGE_REFRESH_RECEIPT_SCHEMA_VERSION",
    "UsageRefreshProviderResult",
    "UsageRefreshReceipt",
    "eligible_usage_providers",
    "is_inline_usage_operation",
    "mark_provider_usage_hot_hint",
    "request_due_usage_refresh",
    "submit_usage_refresh",
    "trigger_usage_refresh_after_limit_event",
    "usage_cli_fingerprint",
    "usage_probe_floor",
    "usage_probe_floors",
    "wait_for_usage_refresh_operations",
]
