"""Rust-backed subscription-capacity usage store facade."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
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
    ProviderUsageIndicatorConfigValidation,
    ProviderUsageIndicatorProjection,
    ProviderUsageAccountContext,
    ProviderUsageMarkHotOutcome,
    ProviderUsageRefreshAdmitOutcome,
    ProviderUsageRefreshDueOutcome,
    ProviderUsageRefreshMarkDueOutcome,
    ProviderUsageRefreshReservation,
    ProviderUsageRefreshReservationOutcome,
    ProviderUsageStoreRead,
    ProviderUsageStoreWriteOutcome,
)
from sase.llm_provider.usage.constants import (
    DEFAULT_USAGE_CADENCE_SECONDS,
    DEFAULT_USAGE_CRITICAL_PERCENT,
    DEFAULT_USAGE_WARN_PERCENT,
    PROVIDER_USAGE_INDICATOR_SCHEMA_VERSION,
)
from sase.llm_provider.usage.errors import ProviderUsageStateError

log = logging.getLogger(__name__)


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
    provider_min_intervals: Mapping[str, float] | None = None,
) -> ProviderUsageStoreRead:
    """Load the public usage snapshot without repairing or rewriting state.

    Per-provider freshness uses ``max(cadence, floor)``. When
    *provider_min_intervals* is None the current plugin floors are used; pass
    an explicit (possibly empty) mapping to override them, e.g. ``{}`` for
    legacy freshness.
    """
    current = time.time() if now is None else now
    if provider_min_intervals is None:
        try:
            from sase.llm_provider.usage._probe_meta import usage_probe_floors

            floors: dict[str, float] | None = usage_probe_floors()
        except Exception:
            floors = None
    else:
        floors = dict(provider_min_intervals)
    binding = require_rust_binding("provider_usage_load")
    return ProviderUsageStoreRead.from_wire(
        binding(
            str(sase_home()),
            current,
            cadence_seconds,
            warn_percent,
            critical_percent,
            floors,
        )
    )


def provider_usage_indicator_schema_version() -> int:
    """Return the Rust usage-indicator projection schema version."""
    binding = require_rust_binding("provider_usage_indicator_schema_version")
    return int(binding())


def provider_usage_validate_indicator_config(
    indicator: object | None = None,
) -> ProviderUsageIndicatorConfigValidation:
    """Validate and normalize ``llm_provider.usage_metrics.indicator``."""
    binding = require_rust_binding("provider_usage_validate_indicator_config")
    return ProviderUsageIndicatorConfigValidation.from_wire(binding(indicator))


def provider_usage_project_indicator(
    snapshot: Mapping[str, object],
    *,
    indicator: object | None = None,
    eligible_providers: Sequence[str] | set[str] | frozenset[str] | None = None,
    now: float | None = None,
    cadence_seconds: float = DEFAULT_USAGE_CADENCE_SECONDS,
    warn_percent: float = DEFAULT_USAGE_WARN_PERCENT,
    critical_percent: float = DEFAULT_USAGE_CRITICAL_PERCENT,
    provider_min_intervals: Mapping[str, float] | None = None,
) -> ProviderUsageIndicatorProjection:
    """Return selected usage-window records from one public snapshot.

    Per-provider freshness uses ``max(cadence_seconds, floor)`` for providers
    named in *provider_min_intervals*; other providers use *cadence_seconds*
    as before. The key is sent to the Rust projection only when provided, so
    callers that pass nothing project exactly as today.
    """
    current = time.time() if now is None else now
    if not isinstance(snapshot, Mapping):
        raise ProviderUsageStateError("provider-usage snapshot is not an object")
    if not is_finite_number(current):
        raise ValueError("now must be finite")
    if eligible_providers is None:
        eligible = None
    else:
        eligible = sorted(dict.fromkeys(str(item) for item in eligible_providers))
    request: dict[str, object] = {
        "schema_version": PROVIDER_USAGE_INDICATOR_SCHEMA_VERSION,
        "snapshot": _indicator_snapshot_wire(snapshot),
        "indicator": indicator,
        "eligible_providers": eligible,
        "now": float(current),
        "cadence_seconds": float(cadence_seconds),
        "warn_percent": float(warn_percent),
        "critical_percent": float(critical_percent),
    }
    if provider_min_intervals is not None:
        request["provider_min_intervals"] = dict(provider_min_intervals)
    binding = require_rust_binding("provider_usage_project_indicator")
    return ProviderUsageIndicatorProjection.from_wire(binding(request))


def _indicator_snapshot_wire(snapshot: Mapping[str, object]) -> dict[str, object]:
    wire = dict(snapshot)
    raw_providers = wire.get("providers")
    if not isinstance(raw_providers, list):
        return wire
    providers: list[object] = []
    changed = False
    for provider in raw_providers:
        if not isinstance(provider, Mapping):
            providers.append(provider)
            continue
        if isinstance(provider.get("attention"), Mapping):
            providers.append(provider)
            continue
        provider_wire = dict(provider)
        provider_name = provider_wire.get("provider")
        provider_wire["attention"] = {
            "kind": "none",
            "provider": provider_name if isinstance(provider_name, str) else "",
            "window_key": None,
        }
        providers.append(provider_wire)
        changed = True
    if changed:
        wire["providers"] = providers
    return wire


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


def provider_usage_window_applies(
    applicability: Mapping[str, object],
    model_id: str | None = None,
) -> str:
    """Return whether a window applies to *model_id*.

    The Rust binding reports ``applies``, ``does_not_apply``, or ``unknown``.
    """
    binding = require_rust_binding("provider_usage_window_applies")
    return str(binding(dict(applicability), model_id))


def provider_usage_summarize_for_model(
    windows: Sequence[Mapping[str, object]],
    model_id: str,
) -> dict[str, Any] | None:
    """Return the tightest applicable public-window summary for *model_id*."""
    binding = require_rust_binding("provider_usage_summarize_for_model")
    result = binding([dict(window) for window in windows], model_id)
    if result is None:
        return None
    if not isinstance(result, dict):
        raise ProviderUsageStateError("usage summary is not an object")
    return result


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


def list_provider_usage_refresh_reservations(
    *,
    now: float | None = None,
) -> tuple[ProviderUsageRefreshReservation, ...]:
    """Return live, unexpired refresh reservations from the usage store."""
    current = time.time() if now is None else now
    binding = require_rust_binding("provider_usage_list_refresh_reservations")
    raw = binding(str(sase_home()), current)
    if not isinstance(raw, list):
        raise ProviderUsageStateError("refresh reservation list is not a list")
    return tuple(ProviderUsageRefreshReservation.from_wire(item) for item in raw)


def evaluate_provider_usage_refresh_due(
    provider: str,
    context_id: str,
    account_generation: int,
    *,
    cadence_seconds: float = DEFAULT_USAGE_CADENCE_SECONDS,
    explicit: bool = False,
    adaptive: bool = False,
    min_interval_seconds: float | None = None,
    cli_fingerprint: str | None = None,
    active_cadence_seconds: float | None = None,
    warn_percent: float | None = None,
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
    if type(adaptive) is not bool:
        raise ValueError("adaptive must be a boolean")
    if min_interval_seconds is not None and not is_finite_number(min_interval_seconds):
        raise ValueError("min_interval_seconds must be a finite number")
    if cli_fingerprint is not None and (
        not isinstance(cli_fingerprint, str) or not cli_fingerprint.strip()
    ):
        raise ValueError("cli_fingerprint must be a non-empty string")
    if active_cadence_seconds is not None and not is_finite_number(
        active_cadence_seconds
    ):
        raise ValueError("active_cadence_seconds must be a finite number")
    if warn_percent is not None and not is_finite_number(warn_percent):
        raise ValueError("warn_percent must be a finite number")
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
                "adaptive": adaptive,
                "min_interval_seconds": (
                    None
                    if min_interval_seconds is None
                    else float(min_interval_seconds)
                ),
                "cli_fingerprint": (
                    None if cli_fingerprint is None else cli_fingerprint.strip()
                ),
                "active_cadence_seconds": (
                    None
                    if active_cadence_seconds is None
                    else float(active_cadence_seconds)
                ),
                "warn_percent": None if warn_percent is None else float(warn_percent),
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
    adaptive: bool = False,
    min_interval_seconds: float | None = None,
    cli_fingerprint: str | None = None,
    active_cadence_seconds: float | None = None,
    warn_percent: float | None = None,
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
    if type(adaptive) is not bool:
        raise ValueError("adaptive must be a boolean")
    if min_interval_seconds is not None and not is_finite_number(min_interval_seconds):
        raise ValueError("min_interval_seconds must be a finite number")
    if cli_fingerprint is not None and (
        not isinstance(cli_fingerprint, str) or not cli_fingerprint.strip()
    ):
        raise ValueError("cli_fingerprint must be a non-empty string")
    if active_cadence_seconds is not None and not is_finite_number(
        active_cadence_seconds
    ):
        raise ValueError("active_cadence_seconds must be a finite number")
    if warn_percent is not None and not is_finite_number(warn_percent):
        raise ValueError("warn_percent must be a finite number")
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
                "adaptive": adaptive,
                "min_interval_seconds": (
                    None
                    if min_interval_seconds is None
                    else float(min_interval_seconds)
                ),
                "cli_fingerprint": (
                    None if cli_fingerprint is None else cli_fingerprint.strip()
                ),
                "active_cadence_seconds": (
                    None
                    if active_cadence_seconds is None
                    else float(active_cadence_seconds)
                ),
                "warn_percent": None if warn_percent is None else float(warn_percent),
            },
            current,
        )
    )


def mark_provider_usage_hot(
    provider: str,
    until: float,
    *,
    context_id: str = "default",
    now: float | None = None,
) -> ProviderUsageMarkHotOutcome | None:
    """Best-effort hot-hint write for *provider* expiring at *until*.

    Never raises: a hint must not add failure modes to launches or limit
    handling. Returns the parsed outcome, or ``None`` when the write was
    skipped or failed (logged at debug level).
    """
    try:
        checked_provider = require_provider_id(provider)
        checked_context = _require_context_id(context_id)
        if not is_finite_number(until):
            raise ValueError("until must be a finite number")
        current = time.time() if now is None else now
        context = prepare_provider_usage_account_context(
            checked_provider, checked_context, now=current
        )
        binding = require_rust_binding("provider_usage_mark_hot")
        return ProviderUsageMarkHotOutcome.from_wire(
            binding(
                str(sase_home()),
                {
                    "provider": checked_provider,
                    "context_id": context.context_id,
                    "account_generation": context.account_generation,
                    "until": float(until),
                },
                current,
            )
        )
    except Exception:
        log.debug("could not mark usage hot for %r", provider, exc_info=True)
        return None


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
    reason_code: str | None = None,
    min_interval_seconds: float | None = None,
    cli_fingerprint: str | None = None,
    adaptive: bool = False,
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
    if reason_code is not None and (
        not isinstance(reason_code, str) or not reason_code.strip()
    ):
        raise ValueError("reason_code must be a non-empty string")
    if min_interval_seconds is not None and not is_finite_number(min_interval_seconds):
        raise ValueError("min_interval_seconds must be a finite number")
    if cli_fingerprint is not None and (
        not isinstance(cli_fingerprint, str) or not cli_fingerprint.strip()
    ):
        raise ValueError("cli_fingerprint must be a non-empty string")
    if type(adaptive) is not bool:
        raise ValueError("adaptive must be a boolean")
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
            "reason_code": (None if reason_code is None else reason_code.strip()),
            "min_interval_seconds": (
                None if min_interval_seconds is None else float(min_interval_seconds)
            ),
            "cli_fingerprint": (
                None if cli_fingerprint is None else cli_fingerprint.strip()
            ),
            "adaptive": adaptive,
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
    "mark_provider_usage_hot",
    "mark_provider_usage_refresh_due",
    "prepare_provider_usage_account_context",
    "provider_usage_format_remaining_text",
    "provider_usage_indicator_schema_version",
    "provider_usage_project_indicator",
    "provider_usage_remaining_percent",
    "provider_usage_state_path",
    "provider_usage_summarize_for_model",
    "provider_usage_validate_indicator_config",
    "provider_usage_window_applies",
    "record_provider_usage_observation",
    "record_provider_usage_refresh_attempt",
    "release_provider_usage_refresh",
    "reserve_provider_usage_refresh",
]
