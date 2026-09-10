"""Best-effort disable expiry sourced from collected usage-window data.

Used by :func:`sase.llm_provider.usage_limit_config.detect_usage_limit` when a
usage-limit error carries no parseable reset hint. Reuses the Rust-backed
window-selection policy (:func:`provider_usage_summarize_for_model` and the
snapshot's per-provider ``summary``) rather than reimplementing
applicability/freshness/limiting-window semantics here; this module only maps
a resolved summary's ``limiting_window_keys`` back to their windows and reads
``resets_at``.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
import math

from sase.llm_provider.usage.constants import DEFAULT_USAGE_CRITICAL_PERCENT
from sase.llm_provider.usage.hints import model_id_from_target
from sase.llm_provider.usage.store import (
    load_provider_usage,
    provider_usage_summarize_for_model,
)

logger = logging.getLogger(__name__)


def usage_window_expires_at(
    provider: str,
    model: str | None,
    *,
    now: float,
) -> float | None:
    """Best-effort disable expiry from collected usage-window data, else None.

    Never raises: any store, binding, or malformed-snapshot problem falls
    through to None so the caller can use the flat disable_seconds fallback.
    """
    try:
        return _usage_window_expires_at(provider, model, now=now)
    except Exception:
        logger.debug(
            "usage-window disable fallback failed for provider %r",
            provider,
            exc_info=True,
        )
        return None


def _usage_window_expires_at(
    provider: str, model: str | None, *, now: float
) -> float | None:
    read = load_provider_usage(now=now)
    providers = read.snapshot.get("providers")
    if not isinstance(providers, list):
        return None
    entry = next(
        (
            item
            for item in providers
            if isinstance(item, Mapping) and item.get("provider") == provider
        ),
        None,
    )
    if entry is None:
        return None

    windows = entry.get("windows")
    if not isinstance(windows, list):
        return None

    if model:
        summary = provider_usage_summarize_for_model(
            windows, model_id_from_target(model)
        )
    else:
        summary = entry.get("summary")
    if not isinstance(summary, Mapping):
        return None

    used_percent = _finite_float(summary.get("used_percent"))
    if used_percent is None or used_percent < DEFAULT_USAGE_CRITICAL_PERCENT:
        return None

    limiting_window_keys = summary.get("limiting_window_keys")
    if not isinstance(limiting_window_keys, list) or not limiting_window_keys:
        return None
    windows_by_key = {
        window.get("key"): window for window in windows if isinstance(window, Mapping)
    }

    best: float | None = None
    for key in limiting_window_keys:
        window = windows_by_key.get(key)
        if window is None:
            continue
        resets_at = _finite_float(window.get("resets_at"))
        if resets_at is None or resets_at <= now:
            continue
        if best is None or resets_at > best:
            best = resets_at
    return best


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


__all__ = ["usage_window_expires_at"]
