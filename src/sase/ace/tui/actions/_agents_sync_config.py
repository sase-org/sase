"""Configuration parsing for ACE agents-repository synchronization checks."""

from __future__ import annotations

from dataclasses import dataclass
import math

DEFAULT_AGENTS_SYNC_CHECK_INTERVAL_SECONDS = 10.0 * 60.0
DEFAULT_AGENTS_SYNC_RECOMPUTE_INTERVAL_SECONDS = 30.0 * 60.0


@dataclass(frozen=True, slots=True)
class _AgentsSyncConfig:
    """Cached settings used by the ACE agents-sync scheduler."""

    check_interval_seconds: float = DEFAULT_AGENTS_SYNC_CHECK_INTERVAL_SECONDS
    recompute_interval_seconds: float = DEFAULT_AGENTS_SYNC_RECOMPUTE_INTERVAL_SECONDS
    indicator: bool = True


def parse_agents_sync_config(value: object) -> _AgentsSyncConfig:
    """Parse the ``ace.agents_sync`` object with safe package fallbacks."""
    if not isinstance(value, dict):
        return _AgentsSyncConfig()
    return _AgentsSyncConfig(
        check_interval_seconds=_minutes_to_seconds(
            value.get("check_interval_minutes"),
            default=DEFAULT_AGENTS_SYNC_CHECK_INTERVAL_SECONDS,
        ),
        recompute_interval_seconds=_minutes_to_seconds(
            value.get("recompute_interval_minutes"),
            default=DEFAULT_AGENTS_SYNC_RECOMPUTE_INTERVAL_SECONDS,
        ),
        indicator=_coerce_bool(value.get("indicator"), default=True),
    )


def _minutes_to_seconds(value: object, *, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    try:
        minutes = float(value)
    except OverflowError:
        return default
    seconds = minutes * 60.0
    return seconds if math.isfinite(seconds) and seconds > 0 else default


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", "none", "disabled"}:
            return False
    return default


__all__ = [
    "DEFAULT_AGENTS_SYNC_CHECK_INTERVAL_SECONDS",
    "DEFAULT_AGENTS_SYNC_RECOMPUTE_INTERVAL_SECONDS",
    "parse_agents_sync_config",
]
