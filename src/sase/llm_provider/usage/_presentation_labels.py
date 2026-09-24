"""Human-readable labels and Rich styles for usage presentation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from sase.core.time import format_local
from sase.llm_provider.usage._presentation_shared import (
    _ATTENTION_STYLES,
    _COLLECTOR_HEALTH_STYLES,
    _STATE_STATUS_LABELS,
    _WINDOW_STATE_LABELS,
    _failure_count,
    _format_remaining_text,
    _number,
    _optional_text,
    _provider_collector_health,
    _string_list,
)


def provider_status_label(provider: Mapping[str, Any]) -> str:
    health_label = _unhealthy_collector_health_label(provider)
    if health_label is not None:
        return health_label
    status = str(provider.get("collection_status") or "unknown")
    label = _STATE_STATUS_LABELS.get(status, status.replace("_", " "))
    reason = _optional_text(provider.get("collection_reason"))
    if reason:
        return f"{label}: {reason.replace('_', ' ')}"
    return label


def window_status_label(window: Mapping[str, Any]) -> str:
    state = str(window.get("vendor_state") or "unknown")
    return _WINDOW_STATE_LABELS.get(state, state.replace("_", " "))


def _collector_health_label(
    health: Mapping[str, Any] | None,
    *,
    reason: Any = None,
) -> str | None:
    """Return a compact human label for a public ``collector_health`` block."""
    if health is None:
        return None
    state = str(health.get("state") or "unknown")
    label = state.replace("_", " ")
    parts = [label]
    reason_text = _optional_text(reason)
    if reason_text is not None:
        parts.append(reason_text.replace("_", " "))
    failures = _failure_count(health)
    if failures is not None and (state != "ok" or failures > 0):
        parts.append(f"{failures}x")
    return " · ".join(parts)


def collector_retry_label(health: Mapping[str, Any] | None, now: float) -> str | None:
    """Return a compact retry label for a ``collector_health`` block.

    Combines ``last_failure_reason`` with the ``retry_at`` instant, for
    example ``"rate limited · retry in 52m"`` or ``"rate limited ·
    retry ~14:05"``. Returns None when the block carries neither.
    """
    if health is None:
        return None
    parts: list[str] = []
    reason = _collector_failure_reason(health)
    if reason is not None:
        parts.append(reason)
    retry = _collector_retry_at_label(health, now)
    if retry is not None:
        parts.append(retry)
    if not parts:
        return None
    return " · ".join(parts)


def _collector_failure_reason(health: Mapping[str, Any]) -> str | None:
    """Return the spaced ``last_failure_reason`` text, if present."""
    reason = _optional_text(health.get("last_failure_reason"))
    if reason is None:
        return None
    return reason.replace("_", " ")


def _collector_retry_at_label(health: Mapping[str, Any], now: float) -> str | None:
    """Return the ``retry_at`` portion of a retry label, if present."""
    retry_at = _number(health.get("retry_at"))
    if retry_at is None:
        return None
    if retry_at > now:
        return f"retry in {duration_label(retry_at - now)}"
    clock = format_local(retry_at, "%H:%M", default="unknown")
    return f"retry ~{clock}"


def _collector_health_style(health: Mapping[str, Any] | None) -> str:
    """Return the Rich style associated with a collector-health block."""
    if health is None:
        return ""
    state = str(health.get("state") or "")
    return _COLLECTOR_HEALTH_STYLES.get(state, "")


def collector_health_style(health: Mapping[str, Any] | None) -> str:
    """Return the public Rich style for a collector-health block."""
    return _collector_health_style(health)


def _window_status_label_for_provider(
    provider: Mapping[str, Any],
    window: Mapping[str, Any],
) -> str:
    health_label = _unhealthy_collector_health_label(provider)
    if health_label is not None:
        return health_label
    return window_status_label(window)


def _window_source_label(window: Mapping[str, Any]) -> str:
    parts = [
        _optional_text(window.get("source")),
        _optional_text(window.get("freshness")),
        applicability_label(window.get("applicability")),
    ]
    return " · ".join(part for part in parts if part)


def _remaining_label(window: Mapping[str, Any]) -> str:
    used = _number(window.get("used_percent"))
    if used is None:
        return "-"
    return _format_remaining_text(used)


def window_label(window: Mapping[str, Any]) -> str:
    label = _optional_text(window.get("label")) or _optional_text(window.get("key"))
    return label or "-"


def reset_label(
    window: Mapping[str, Any],
    now: float,
    *,
    verbose: bool,
) -> str:
    resets_at = _number(window.get("resets_at"))
    reset_passed = window.get("reset_passed") is True
    if resets_at is None:
        return "unknown"
    if reset_passed or resets_at <= now:
        return "reset passed"
    relative = f"in {duration_label(resets_at - now)}"
    if verbose:
        return f"{relative} ({timestamp_label(resets_at, now)})"
    return relative


def age_label(window: Mapping[str, Any]) -> str:
    age = _number(window.get("age_seconds"))
    if age is None:
        return "unknown"
    return duration_label(age)


def _age_from_timestamp(value: Any, now: float) -> str:
    timestamp = _number(value)
    if timestamp is None:
        return "unknown"
    return duration_label(max(now - timestamp, 0.0))


def timestamp_label(value: Any, now: float) -> str:
    timestamp = _number(value)
    if timestamp is None:
        return "unknown"
    if not math.isfinite(timestamp):
        return "unknown"
    absolute = format_local(timestamp, "%Y-%m-%d %H:%M:%S %Z", default="unknown")
    if absolute == "unknown":
        return "unknown"
    if timestamp > now:
        return absolute
    return f"{absolute} ({duration_label(now - timestamp)} ago)"


def duration_label(seconds: float) -> str:
    if not math.isfinite(seconds):
        return "unknown"
    whole = max(int(round(seconds)), 0)
    if whole < 60:
        return f"{whole}s"
    minutes = whole // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        remainder = minutes % 60
        return f"{hours}h" if remainder == 0 else f"{hours}h {remainder}m"
    days = hours // 24
    return f"{days}d"


def applicability_label(value: Any) -> str:
    if not isinstance(value, Mapping):
        return "unknown"
    kind = _optional_text(value.get("kind")) or "unknown"
    if kind == "account":
        return "account"
    if kind == "models":
        models = _string_list(value.get("model_ids"))
        return "models:" + ",".join(models) if models else "models"
    if kind == "model_family":
        family = _optional_text(value.get("family"))
        return f"family:{family}" if family else "model_family"
    if kind == "product":
        product = _optional_text(value.get("product"))
        models = _string_list(value.get("model_ids"))
        suffix = f":{','.join(models)}" if models else ""
        return f"product:{product or 'unknown'}{suffix}"
    return kind


def provider_style(provider: Mapping[str, Any]) -> str:
    health_style = _collector_health_style(_provider_collector_health(provider))
    if health_style:
        return health_style
    status = str(provider.get("collection_status") or "")
    if status in {"error", "unauthenticated"}:
        return "yellow"
    return ""


def _provider_window_style(
    provider: Mapping[str, Any],
    window: Mapping[str, Any],
) -> str:
    health_style = _collector_health_style(_provider_collector_health(provider))
    if health_style:
        return health_style
    return _window_style(window)


def _window_style(window: Mapping[str, Any]) -> str:
    attention = str(window.get("attention") or "")
    if attention in _ATTENTION_STYLES:
        return _ATTENTION_STYLES[attention]
    state = str(window.get("vendor_state") or "")
    if state == "rejected":
        return "bold red"
    if state == "warning":
        return "yellow"
    return ""


def diagnostic_line(diagnostic: Mapping[str, Any]) -> str:
    provider = diagnostic.get("provider") or "store"
    message = diagnostic.get("message") or ""
    return f"{provider}: {message}"


def _unhealthy_collector_health_label(provider: Mapping[str, Any]) -> str | None:
    health = _provider_collector_health(provider)
    if health is None:
        return None
    state = str(health.get("state") or "")
    if state not in {"degraded", "failing"}:
        return None
    return _collector_health_label(health, reason=provider.get("collection_reason"))
