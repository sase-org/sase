"""Cached subscription-usage snapshot loading for the ACE Providers home."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import time
from typing import Any

from sase.llm_provider.usage.config import (
    get_usage_metrics_settings,
    usage_metrics_feature_enabled,
)
from sase.llm_provider.usage.store import (
    ProviderUsageStoreDiagnostic,
    load_provider_usage,
)


@dataclass(frozen=True)
class ProviderUsageViewSnapshot:
    """One immutable cached-usage snapshot for the ACE Usage view."""

    providers: tuple[Mapping[str, Any], ...]
    diagnostics: tuple[ProviderUsageStoreDiagnostic, ...]
    captured_at: float
    feature_enabled: bool
    load_error: str | None = None


def load_usage_view_snapshot(now: float | None = None) -> ProviderUsageViewSnapshot:
    """Load the cached usage snapshot from disk. Never submits a probe."""
    captured_at = time.time() if now is None else float(now)
    feature_enabled = usage_metrics_feature_enabled()
    settings = get_usage_metrics_settings()
    try:
        read = load_provider_usage(
            now=captured_at,
            cadence_seconds=settings.refresh_seconds,
            warn_percent=settings.warn_percent,
            critical_percent=settings.critical_percent,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as a view-level diagnostic.
        return ProviderUsageViewSnapshot(
            providers=(),
            diagnostics=(),
            captured_at=captured_at,
            feature_enabled=feature_enabled,
            load_error=str(exc),
        )
    raw_providers = read.snapshot.get("providers")
    providers = tuple(
        item
        for item in (raw_providers if isinstance(raw_providers, list) else [])
        if isinstance(item, Mapping)
    )
    return ProviderUsageViewSnapshot(
        providers=providers,
        diagnostics=read.diagnostics,
        captured_at=captured_at,
        feature_enabled=feature_enabled,
    )


__all__ = ["ProviderUsageViewSnapshot", "load_usage_view_snapshot"]
