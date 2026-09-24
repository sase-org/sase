"""Shared constants and receipt types for subscription-usage refresh."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

USAGE_REFRESH_OPERATION = "usage.refresh"
INLINE_USAGE_OPERATION_PREFIX = "usage-job:"
USAGE_REFRESH_EXECUTIONS = ("proc", "inline")
USAGE_INLINE_WAIT_POLL_SECONDS = 0.5
USAGE_REFRESH_RECEIPT_SCHEMA_VERSION = 1
MAX_CONCURRENT_USAGE_PROBES = 3
USAGE_REFRESH_PROVIDER_DEADLINE_SECONDS = 20.0
USAGE_REFRESH_BATCH_DEADLINE_SECONDS = 45.0
USAGE_REFRESH_LEASE_TTL_SECONDS = 75.0
USAGE_REFRESH_CONTEXT_ID = "default"
USAGE_REFRESH_ORIGINS = ("ace", "axe", "cli")
HOT_HINT_TTL_SECONDS = 900.0


@dataclass(frozen=True)
class UsageRefreshProviderResult:
    """One provider's place in a batch receipt."""

    provider: str
    status: str
    reason: str | None
    operation_id: str | None
    lease_id: str | None = None
    context_id: str = USAGE_REFRESH_CONTEXT_ID
    account_generation: int = 1
    due_at: float | None = None

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-ready mapping."""
        return {
            "account_generation": self.account_generation,
            "context_id": self.context_id,
            "due_at": self.due_at,
            "lease_id": self.lease_id,
            "operation_id": self.operation_id,
            "provider": self.provider,
            "reason": self.reason,
            "status": self.status,
        }


@dataclass(frozen=True)
class UsageRefreshReceipt:
    """Batch receipt covering every requested provider."""

    schema_version: int
    origin: str
    operation_ids: tuple[str, ...]
    providers: tuple[UsageRefreshProviderResult, ...]
    inline_results: tuple[Mapping[str, Any], ...] = ()

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-ready mapping."""
        return {
            "operation_ids": list(self.operation_ids),
            "origin": self.origin,
            "providers": [item.to_json() for item in self.providers],
            "schema_version": self.schema_version,
        }

    @property
    def started(self) -> bool:
        """Return whether this receipt started or joined any durable work."""
        return bool(self.operation_ids)


def is_inline_usage_operation(operation_id: str) -> bool:
    """Return whether *operation_id* names an inline usage job, not a proc."""
    return isinstance(operation_id, str) and operation_id.startswith(
        INLINE_USAGE_OPERATION_PREFIX
    )
