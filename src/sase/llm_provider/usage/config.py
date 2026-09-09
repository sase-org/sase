"""Parse ``llm_provider.usage_metrics`` configuration."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Mapping

from sase.core.rust import require_rust_binding
from sase.llm_provider.usage.types import UsageSkipReason

log = logging.getLogger(__name__)

DEFAULT_USAGE_ENABLED = True
DEFAULT_REFRESH_SECONDS = 300.0
MIN_REFRESH_SECONDS = 60.0
DEFAULT_WARN_PERCENT = 75.0
DEFAULT_CRITICAL_PERCENT = 90.0


@dataclass(frozen=True)
class UsageMetricsSettings:
    """Resolved machine-local usage collection preferences."""

    enabled: bool = DEFAULT_USAGE_ENABLED
    refresh_seconds: float = DEFAULT_REFRESH_SECONDS
    warn_percent: float = DEFAULT_WARN_PERCENT
    critical_percent: float = DEFAULT_CRITICAL_PERCENT
    providers: Mapping[str, bool] = field(default_factory=dict)

    def provider_enabled(self, provider: str) -> bool:
        """Return whether *provider* is allowed to collect, given the global flag."""
        if not self.enabled:
            return False
        override = self.providers.get(provider)
        if override is None:
            return True
        return override


def get_usage_metrics_settings() -> UsageMetricsSettings:
    """Load and validate ``llm_provider.usage_metrics``."""
    section = _load_usage_metrics_section()
    defaults = UsageMetricsSettings()
    enabled = _as_bool(section.get("enabled"), defaults.enabled)
    refresh_seconds = _as_number(
        section.get("refresh_seconds"), defaults.refresh_seconds
    )
    warn_percent = _as_number(section.get("warn_percent"), defaults.warn_percent)
    critical_percent = _as_number(
        section.get("critical_percent"), defaults.critical_percent
    )
    try:
        _validate_metrics(refresh_seconds, warn_percent, critical_percent)
    except (TypeError, ValueError, AttributeError) as exc:
        log.warning("ignoring invalid llm_provider.usage_metrics values: %s", exc)
        refresh_seconds = defaults.refresh_seconds
        warn_percent = defaults.warn_percent
        critical_percent = defaults.critical_percent
    return UsageMetricsSettings(
        enabled=enabled,
        refresh_seconds=refresh_seconds,
        warn_percent=warn_percent,
        critical_percent=critical_percent,
        providers=_provider_overrides(section.get("providers")),
    )


def collection_skip_reason(provider: str) -> UsageSkipReason | None:
    """Return why collection is inactive, or ``None`` when probes may run."""
    settings = get_usage_metrics_settings()
    if not settings.enabled:
        return "config_disabled"
    if not settings.provider_enabled(provider):
        return "provider_disabled"
    return None


def _load_usage_metrics_section() -> dict[str, Any]:
    from sase.llm_provider.config import get_llm_provider_config

    section = get_llm_provider_config().get("usage_metrics", {}) or {}
    if not isinstance(section, dict):
        return {}
    return section


def _provider_overrides(raw: object) -> dict[str, bool]:
    if not isinstance(raw, dict):
        return {}
    overrides: dict[str, bool] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(value, dict):
            continue
        if "enabled" not in value:
            continue
        enabled = value.get("enabled")
        if isinstance(enabled, bool):
            overrides[name] = enabled
    return overrides


def _validate_metrics(
    refresh_seconds: float, warn_percent: float, critical_percent: float
) -> None:
    project = require_rust_binding("provider_usage_project_snapshot")
    project([], time.time(), refresh_seconds, warn_percent, critical_percent)


def _as_bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _as_number(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number
