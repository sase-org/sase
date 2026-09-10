"""Lock-free display cache for subscription-usage snapshots.

Picker construction and the top-bar tick must not take the usage-store lock or
parse JSON on the UI thread. :func:`cached_usage_peek` is memory-only.
:func:`refresh_usage_peek_cache` is the worker-thread load.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.config.core import current_config_token
from sase.llm_provider.usage.config import (
    UsageIndicatorSettings,
    UsageMetricsSettings,
    get_usage_indicator_settings,
    get_usage_metrics_settings,
)
from sase.llm_provider.usage.store import (
    ProviderUsageIndicatorProjection,
    load_provider_usage,
    provider_usage_project_indicator,
    provider_usage_state_path,
)

_PEEK_STAT_FLOOR_SECONDS = 0.5


@dataclass(frozen=True)
class UsagePeekSnapshot:
    """Immutable memory-only snapshot for usage indicator consumers."""

    snapshot: Mapping[str, Any]
    providers: tuple[Mapping[str, Any], ...]
    eligible: frozenset[str]
    metrics: UsageMetricsSettings
    indicator: UsageIndicatorSettings
    captured_at: float


_peek_lock = threading.Lock()
_peek_token: tuple[Any, ...] | None = None
_peek_state_token: tuple[int, int] | None = None
_peek_deadline = 0.0
_peek_providers: tuple[Mapping[str, Any], ...] = ()
_peek_eligible: frozenset[str] = frozenset()
_peek_snapshot: Mapping[str, Any] = {
    "schema_version": 1,
    "generated_at": 0.0,
    "collection_health": "empty",
    "providers": [],
    "attention": None,
}
_peek_metrics = UsageMetricsSettings()
_peek_indicator = UsageIndicatorSettings()
_peek_captured_at = 0.0


def usage_attention_enabled() -> bool:
    """Return whether contextual usage hints and attention should appear."""
    return (
        get_usage_metrics_settings().enabled and get_usage_indicator_settings().enabled
    )


def cached_usage_peek() -> tuple[tuple[Mapping[str, Any], ...], frozenset[str]]:
    """Return the last loaded providers and eligible set. Never reads disk."""
    if not usage_attention_enabled():
        return (), frozenset()
    with _peek_lock:
        return _peek_providers, _peek_eligible


def cached_usage_display_snapshot() -> UsagePeekSnapshot:
    """Return the last loaded usage display snapshot. Never reads disk."""
    if not usage_attention_enabled():
        return _empty_usage_peek_snapshot(time.time())
    with _peek_lock:
        return UsagePeekSnapshot(
            snapshot=_peek_snapshot,
            providers=_peek_providers,
            eligible=_peek_eligible,
            metrics=_peek_metrics,
            indicator=_peek_indicator,
            captured_at=_peek_captured_at,
        )


def cached_usage_indicator_projection(
    *,
    now: float | None = None,
) -> ProviderUsageIndicatorProjection:
    """Project selected usage-window records from the memory-only peek snapshot."""
    display = cached_usage_display_snapshot()
    captured_at = time.time() if now is None else float(now)
    return provider_usage_project_indicator(
        display.snapshot,
        indicator=display.indicator.raw,
        eligible_providers=display.eligible,
        now=captured_at,
        cadence_seconds=display.metrics.refresh_seconds,
        warn_percent=display.metrics.warn_percent,
        critical_percent=display.metrics.critical_percent,
    )


def usage_peek_change_token() -> tuple[Any, ...]:
    """Return a config-and-state change token, checking file metadata on a floor."""
    global _peek_deadline, _peek_state_token, _peek_token  # noqa: PLW0603

    config_token = current_config_token()
    current_monotonic = time.monotonic()
    with _peek_lock:
        if current_monotonic >= _peek_deadline:
            _peek_deadline = current_monotonic + _PEEK_STAT_FLOOR_SECONDS
            try:
                path = provider_usage_state_path()
                stat = path.stat()
            except OSError:
                _peek_state_token = None
            else:
                _peek_state_token = (stat.st_mtime_ns, stat.st_size)
        token = (config_token, _peek_state_token)
        _peek_token = token
        return _peek_token


def refresh_usage_peek_cache(
    *,
    now: float | None = None,
) -> tuple[tuple[Mapping[str, Any], ...], frozenset[str]]:
    """Load the public snapshot and eligible providers. Call off the UI thread."""
    global _peek_captured_at, _peek_eligible, _peek_indicator  # noqa: PLW0603
    global _peek_metrics, _peek_providers, _peek_snapshot  # noqa: PLW0603

    settings = get_usage_metrics_settings()
    indicator = get_usage_indicator_settings()
    if not settings.enabled or not indicator.enabled:
        _clear_usage_peek_cache()
        return (), frozenset()
    captured_at = time.time() if now is None else float(now)
    try:
        read = load_provider_usage(
            now=captured_at,
            cadence_seconds=settings.refresh_seconds,
            warn_percent=settings.warn_percent,
            critical_percent=settings.critical_percent,
        )
    except Exception:
        snapshot: Mapping[str, Any] = _empty_public_snapshot(captured_at)
        providers: tuple[Mapping[str, Any], ...] = ()
    else:
        snapshot = read.snapshot
        raw = read.snapshot.get("providers")
        providers = tuple(
            item
            for item in (raw if isinstance(raw, list) else ())
            if isinstance(item, Mapping)
        )
    try:
        from sase.llm_provider.usage.refresh import eligible_usage_providers

        eligible = frozenset(eligible_usage_providers())
    except Exception:
        eligible = frozenset()
    with _peek_lock:
        _peek_snapshot = snapshot
        _peek_providers = providers
        _peek_eligible = eligible
        _peek_metrics = settings
        _peek_indicator = indicator
        _peek_captured_at = captured_at
    return providers, eligible


def _clear_usage_peek_cache() -> None:
    """Drop cached providers. Tests use this after planting state."""
    global _peek_captured_at, _peek_deadline, _peek_eligible  # noqa: PLW0603
    global _peek_indicator, _peek_metrics, _peek_providers  # noqa: PLW0603
    global _peek_snapshot, _peek_state_token, _peek_token  # noqa: PLW0603

    with _peek_lock:
        _peek_token = None
        _peek_state_token = None
        _peek_deadline = 0.0
        _peek_providers = ()
        _peek_eligible = frozenset()
        _peek_snapshot = _empty_public_snapshot(0.0)
        _peek_metrics = UsageMetricsSettings()
        _peek_indicator = UsageIndicatorSettings()
        _peek_captured_at = 0.0


def _empty_usage_peek_snapshot(now: float) -> UsagePeekSnapshot:
    return UsagePeekSnapshot(
        snapshot=_empty_public_snapshot(now),
        providers=(),
        eligible=frozenset(),
        metrics=UsageMetricsSettings(),
        indicator=UsageIndicatorSettings(enabled=False, raw={"enabled": False}),
        captured_at=now,
    )


def _empty_public_snapshot(now: float) -> Mapping[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": now,
        "collection_health": "empty",
        "providers": [],
        "attention": None,
    }


__all__ = [
    "UsagePeekSnapshot",
    "cached_usage_display_snapshot",
    "cached_usage_indicator_projection",
    "cached_usage_peek",
    "refresh_usage_peek_cache",
    "usage_attention_enabled",
    "usage_peek_change_token",
]
