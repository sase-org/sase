"""Rust-backed subscription-capacity usage store facade."""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding
from sase.llm_provider.provider_disable import (
    is_finite_number,
    is_provider_id,
    require_provider_id,
)
from sase.llm_provider.usage._wire import (
    ProviderUsageAccountContext,
    ProviderUsageRefreshAdmitOutcome,
    ProviderUsageRefreshDueOutcome,
    ProviderUsageRefreshMarkDueOutcome,
    ProviderUsageRefreshReservationOutcome,
    ProviderUsageStoreRead,
    ProviderUsageStoreWriteOutcome,
)
from sase.llm_provider.usage.constants import (
    DEFAULT_USAGE_CADENCE_SECONDS,
    DEFAULT_USAGE_CRITICAL_PERCENT,
    DEFAULT_USAGE_WARN_PERCENT,
)
from sase.llm_provider.usage.errors import ProviderUsageStateError


def provider_usage_state_path() -> Path:
    """Return the canonical usage-state path under ``sase_home``."""
    binding = require_rust_binding("provider_usage_state_path")
    return Path(str(binding(str(sase_home()))))


def load_provider_usage(
    *,
    now: float | None = None,
    cadence_seconds: float = DEFAULT_USAGE_CADENCE_SECONDS,
    warn_percent: float = DEFAULT_USAGE_WARN_PERCENT,
    critical_percent: float = DEFAULT_USAGE_CRITICAL_PERCENT,
) -> ProviderUsageStoreRead:
    """Load the public usage snapshot without repairing or rewriting state."""
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_load")
    return ProviderUsageStoreRead.from_wire(
        binding(
            str(sase_home()),
            current,
            cadence_seconds,
            warn_percent,
            critical_percent,
        )
    )


def provider_usage_remaining_percent(used_percent: float) -> float:
    """Return the remaining percentage using the Rust domain policy."""
    if not is_finite_number(used_percent):
        raise ValueError("used_percent must be finite")
    binding = require_rust_binding("provider_usage_remaining_percent")
    return float(binding(float(used_percent)))


def provider_usage_format_remaining_text(used_percent: float) -> str:
    """Return user-facing remaining text using the Rust domain policy."""
    if not is_finite_number(used_percent):
        raise ValueError("used_percent must be finite")
    binding = require_rust_binding("provider_usage_format_remaining_text")
    return str(binding(float(used_percent)))


def record_provider_usage_observation(
    observation: Mapping[str, object],
    *,
    now: float | None = None,
) -> ProviderUsageStoreWriteOutcome:
    """Validate, merge, and persist one normalized provider observation."""
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_record_observation")
    return ProviderUsageStoreWriteOutcome.from_wire(
        binding(str(sase_home()), dict(observation), current)
    )


def prepare_provider_usage_account_context(
    provider: str,
    context_id: str,
    *,
    now: float | None = None,
) -> ProviderUsageAccountContext:
    """Prepare or advance the generation fence for a provider account context."""
    provider = require_provider_id(provider)
    context_id = _require_context_id(context_id)
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_prepare_account_context")
    return ProviderUsageAccountContext.from_wire(
        binding(str(sase_home()), provider, context_id, current)
    )


def reserve_provider_usage_refresh(
    provider: str,
    context_id: str,
    account_generation: int,
    operation_id: str,
    ttl_seconds: float,
    *,
    now: float | None = None,
) -> ProviderUsageRefreshReservationOutcome:
    """Reserve or join refresh work for one provider/account generation."""
    provider = require_provider_id(provider)
    context_id = _require_context_id(context_id)
    operation_id = _require_context_id(operation_id)
    account_generation = _require_account_generation(account_generation)
    if not is_finite_number(ttl_seconds) or float(ttl_seconds) <= 0.0:
        raise ValueError("ttl_seconds must be a finite positive number")
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_reserve_refresh")
    return ProviderUsageRefreshReservationOutcome.from_wire(
        binding(
            str(sase_home()),
            {
                "provider": provider,
                "context_id": context_id,
                "account_generation": account_generation,
                "operation_id": operation_id,
                "ttl_seconds": float(ttl_seconds),
            },
            current,
        )
    )


def release_provider_usage_refresh(
    provider: str,
    context_id: str,
    account_generation: int,
    lease_id: str,
    *,
    now: float | None = None,
) -> bool:
    """Release a refresh reservation when the lease still matches."""
    provider = require_provider_id(provider)
    context_id = _require_context_id(context_id)
    account_generation = _require_account_generation(account_generation)
    lease_id = _require_context_id(lease_id)
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_release_refresh")
    return bool(
        binding(
            str(sase_home()),
            provider,
            context_id,
            account_generation,
            lease_id,
            current,
        )
    )


def evaluate_provider_usage_refresh_due(
    provider: str,
    context_id: str,
    account_generation: int,
    *,
    cadence_seconds: float = DEFAULT_USAGE_CADENCE_SECONDS,
    explicit: bool = False,
    now: float | None = None,
) -> ProviderUsageRefreshDueOutcome:
    """Return whether *provider* is due without reserving work."""
    provider = require_provider_id(provider)
    context_id = _require_context_id(context_id)
    account_generation = _require_account_generation(account_generation)
    if not is_finite_number(cadence_seconds) or float(cadence_seconds) <= 0.0:
        raise ValueError("cadence_seconds must be a finite positive number")
    if type(explicit) is not bool:
        raise ValueError("explicit must be a boolean")
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_refresh_due")
    return ProviderUsageRefreshDueOutcome.from_wire(
        binding(
            str(sase_home()),
            {
                "provider": provider,
                "context_id": context_id,
                "account_generation": account_generation,
                "cadence_seconds": float(cadence_seconds),
                "explicit": explicit,
            },
            current,
        )
    )


def admit_provider_usage_refresh(
    provider: str,
    context_id: str,
    account_generation: int,
    operation_id: str,
    ttl_seconds: float,
    *,
    cadence_seconds: float = DEFAULT_USAGE_CADENCE_SECONDS,
    explicit: bool = False,
    now: float | None = None,
) -> ProviderUsageRefreshAdmitOutcome:
    """Admit, join, or defer refresh work for one provider/account generation."""
    provider = require_provider_id(provider)
    context_id = _require_context_id(context_id)
    operation_id = _require_context_id(operation_id)
    account_generation = _require_account_generation(account_generation)
    if not is_finite_number(ttl_seconds) or float(ttl_seconds) <= 0.0:
        raise ValueError("ttl_seconds must be a finite positive number")
    if not is_finite_number(cadence_seconds) or float(cadence_seconds) <= 0.0:
        raise ValueError("cadence_seconds must be a finite positive number")
    if type(explicit) is not bool:
        raise ValueError("explicit must be a boolean")
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_admit_refresh")
    return ProviderUsageRefreshAdmitOutcome.from_wire(
        binding(
            str(sase_home()),
            {
                "provider": provider,
                "context_id": context_id,
                "account_generation": account_generation,
                "operation_id": operation_id,
                "ttl_seconds": float(ttl_seconds),
                "cadence_seconds": float(cadence_seconds),
                "explicit": explicit,
            },
            current,
        )
    )


def mark_provider_usage_refresh_due(
    provider: str,
    context_id: str,
    account_generation: int,
    reason: str,
    *,
    due_at: float | None = None,
    now: float | None = None,
) -> ProviderUsageRefreshMarkDueOutcome:
    """Mark *provider* due once for *reason*, optionally at a future time."""
    provider = require_provider_id(provider)
    context_id = _require_context_id(context_id)
    account_generation = _require_account_generation(account_generation)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must be a non-empty string")
    if due_at is not None and not is_finite_number(due_at):
        raise ValueError("due_at must be a finite number")
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_mark_refresh_due")
    return ProviderUsageRefreshMarkDueOutcome.from_wire(
        binding(
            str(sase_home()),
            {
                "provider": provider,
                "context_id": context_id,
                "account_generation": account_generation,
                "reason": reason.strip(),
                "due_at": None if due_at is None else float(due_at),
            },
            current,
        )
    )


def record_provider_usage_refresh_attempt(
    provider: str,
    context_id: str,
    account_generation: int,
    outcome: str,
    *,
    retry_after_seconds: float | None = None,
    cadence_seconds: float = DEFAULT_USAGE_CADENCE_SECONDS,
    now: float | None = None,
) -> dict[str, Any]:
    """Record backoff/cooldown after one provider refresh attempt."""
    provider = require_provider_id(provider)
    context_id = _require_context_id(context_id)
    account_generation = _require_account_generation(account_generation)
    if not isinstance(outcome, str) or not outcome.strip():
        raise ValueError("outcome must be a non-empty string")
    if retry_after_seconds is not None and (
        not is_finite_number(retry_after_seconds) or float(retry_after_seconds) < 0.0
    ):
        raise ValueError("retry_after_seconds must be a finite nonnegative number")
    if not is_finite_number(cadence_seconds) or float(cadence_seconds) <= 0.0:
        raise ValueError("cadence_seconds must be a finite positive number")
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_record_refresh_attempt")
    recorded = binding(
        str(sase_home()),
        {
            "provider": provider,
            "context_id": context_id,
            "account_generation": account_generation,
            "outcome": outcome.strip(),
            "retry_after_seconds": (
                None if retry_after_seconds is None else float(retry_after_seconds)
            ),
            "cadence_seconds": float(cadence_seconds),
        },
        current,
    )
    if not isinstance(recorded, dict):
        raise ProviderUsageStateError("refresh attempt record is not an object")
    return recorded


def _require_context_id(value: object) -> str:
    """Validate an opaque provider context, operation, or lease identifier."""
    if not isinstance(value, str):
        raise ValueError("context identifier must be a string")
    if not is_provider_id(value):
        raise ValueError("context identifier must be non-empty plain text")
    return value


def _require_account_generation(value: object) -> int:
    """Validate a generation fence value."""
    if type(value) is not int or value < 0:
        raise ValueError("account_generation must be a nonnegative integer")
    return value


__all__ = [
    "admit_provider_usage_refresh",
    "evaluate_provider_usage_refresh_due",
    "load_provider_usage",
    "mark_provider_usage_refresh_due",
    "prepare_provider_usage_account_context",
    "provider_usage_format_remaining_text",
    "provider_usage_remaining_percent",
    "provider_usage_state_path",
    "record_provider_usage_observation",
    "record_provider_usage_refresh_attempt",
    "release_provider_usage_refresh",
    "reserve_provider_usage_refresh",
]
