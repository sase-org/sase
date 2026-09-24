"""Shared primitives for cached subscription-usage presentation."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

_STATE_STATUS_LABELS: Mapping[str, str] = {
    "ok": "ok",
    "error": "error",
    "unsupported": "unsupported",
    "unauthenticated": "logged out",
    "not_applicable": "not applicable",
    "no_observations": "no observations",
    "disabled": "disabled",
    "deferred": "deferred",
}
_WINDOW_STATE_LABELS: Mapping[str, str] = {
    "allowed": "ok",
    "warning": "warning",
    "rejected": "exhausted",
    "unknown": "unknown",
}
_ATTENTION_STYLES: Mapping[str, str] = {
    "rejected": "bold red",
    "very_low": "bold red",
    "low": "yellow",
    "collection_problem": "yellow",
}
_COLLECTOR_HEALTH_STYLES: Mapping[str, str] = {
    "degraded": "yellow",
    "failing": "bold #FFAF5F",
}


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def nonblank_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def provider_collector_health(provider: Mapping[str, Any]) -> Mapping[str, Any] | None:
    health = provider.get("collector_health")
    return health if isinstance(health, Mapping) else None


def failure_count(health: Mapping[str, Any]) -> int | None:
    value = health.get("consecutive_failures")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if not math.isfinite(float(value)):
        return None
    return max(int(value), 0)


def format_remaining_text(used: float) -> str:
    """Return user-facing remaining text for a ``used_percent`` value.

    Resolved through the ``sase.llm_provider.usage.presentation`` facade at
    call time (never imported at module top, to avoid a cycle) so tests can
    monkeypatch ``presentation.provider_usage_format_remaining_text``.
    """
    from sase.llm_provider.usage import presentation

    return presentation.provider_usage_format_remaining_text(used)
