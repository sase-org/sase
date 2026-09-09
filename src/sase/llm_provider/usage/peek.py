"""Lock-free display cache for subscription-usage snapshots.

Picker construction and the top-bar tick must not take the usage-store lock or
parse JSON on the UI thread. :func:`cached_usage_peek` is memory-only.
:func:`refresh_usage_peek_cache` is the worker-thread load.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.llm_provider.usage.config import get_usage_metrics_settings
from sase.llm_provider.usage.store import load_provider_usage, provider_usage_state_path

_PEEK_STAT_FLOOR_SECONDS = 0.5

_peek_lock = threading.Lock()
_peek_path: Path | None = None
_peek_token: tuple[int, int] | None = None
_peek_deadline = 0.0
_peek_providers: tuple[Mapping[str, Any], ...] = ()
_peek_eligible: frozenset[str] = frozenset()


def usage_attention_enabled() -> bool:
    """Return whether contextual usage hints and attention should appear."""
    return get_usage_metrics_settings().enabled


def cached_usage_peek() -> tuple[tuple[Mapping[str, Any], ...], frozenset[str]]:
    """Return the last loaded providers and eligible set. Never reads disk."""
    if not usage_attention_enabled():
        return (), frozenset()
    with _peek_lock:
        return _peek_providers, _peek_eligible


def usage_peek_change_token() -> tuple[int, int] | None:
    """Return a stat-only change token, checking filesystem metadata on a floor."""
    global _peek_deadline, _peek_path, _peek_token  # noqa: PLW0603

    current_monotonic = time.monotonic()
    with _peek_lock:
        if current_monotonic < _peek_deadline:
            return _peek_token
        _peek_deadline = current_monotonic + _PEEK_STAT_FLOOR_SECONDS
        try:
            path = provider_usage_state_path()
            stat = path.stat()
        except OSError:
            _peek_path = None
            _peek_token = None
            return None
        token = (stat.st_mtime_ns, stat.st_size)
        _peek_path = path
        if token != _peek_token:
            _peek_token = token
        return _peek_token


def refresh_usage_peek_cache(
    *,
    now: float | None = None,
) -> tuple[tuple[Mapping[str, Any], ...], frozenset[str]]:
    """Load the public snapshot and eligible providers. Call off the UI thread."""
    global _peek_eligible, _peek_providers  # noqa: PLW0603

    if not usage_attention_enabled():
        _clear_usage_peek_cache()
        return (), frozenset()
    settings = get_usage_metrics_settings()
    captured_at = time.time() if now is None else float(now)
    try:
        read = load_provider_usage(
            now=captured_at,
            cadence_seconds=settings.refresh_seconds,
            warn_percent=settings.warn_percent,
            critical_percent=settings.critical_percent,
        )
    except Exception:
        providers: tuple[Mapping[str, Any], ...] = ()
    else:
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
        _peek_providers = providers
        _peek_eligible = eligible
    return providers, eligible


def _clear_usage_peek_cache() -> None:
    """Drop cached providers. Tests use this after planting state."""
    global _peek_deadline, _peek_eligible, _peek_path, _peek_providers  # noqa: PLW0603
    global _peek_token  # noqa: PLW0603

    with _peek_lock:
        _peek_path = None
        _peek_token = None
        _peek_deadline = 0.0
        _peek_providers = ()
        _peek_eligible = frozenset()


__all__ = [
    "cached_usage_peek",
    "refresh_usage_peek_cache",
    "usage_attention_enabled",
    "usage_peek_change_token",
]
