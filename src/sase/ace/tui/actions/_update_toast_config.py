"""Configuration parsing for automatic ACE update checks and toasts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sase.updates import DEFAULT_UPDATE_STATUS_TTL_SECONDS

# Fallbacks used only when a TTL key is present but unparsable; both resolve to
# the 10-minute default so a garbage override never silently re-enables a day.
_DEFAULT_CHECK_TTL_MINUTES = DEFAULT_UPDATE_STATUS_TTL_SECONDS / 60.0
_DEFAULT_CHECK_TTL_HOURS = DEFAULT_UPDATE_STATUS_TTL_SECONDS / 3600.0
_DEFAULT_STARTUP_TOAST_MAX_COMMITS = 20
_DEFAULT_POST_UPDATE_TOAST_MAX_COMMITS = 5
_AUTOMATIC_UPDATE_CHECK_INTERVAL_SECONDS = 600.0
_DEFAULT_RECOMPUTE_INTERVAL_MINUTES = 60.0
_DEFAULT_RECOMPUTE_INTERVAL_SECONDS = _DEFAULT_RECOMPUTE_INTERVAL_MINUTES * 60.0


@dataclass(frozen=True)
class UpdateToastConfig:
    """Config values controlling automatic update checks and update toasts."""

    startup_toast: bool = True
    post_update_toast: bool = True
    post_update_toast_diffstat: bool = True
    post_update_toast_commits: bool = True
    post_update_toast_max_commits: int = _DEFAULT_POST_UPDATE_TOAST_MAX_COMMITS
    indicator: bool = True
    check_ttl_seconds: float = DEFAULT_UPDATE_STATUS_TTL_SECONDS
    recompute_interval_seconds: float = _DEFAULT_RECOMPUTE_INTERVAL_SECONDS
    incoming_commits_enabled: bool = True
    startup_toast_max_commits: int = _DEFAULT_STARTUP_TOAST_MAX_COMMITS


def parse_update_toast_config(data: object) -> UpdateToastConfig:
    """Parse automatic update-check config from merged SASE config data."""
    if not isinstance(data, dict):
        return UpdateToastConfig()
    ace = data.get("ace")
    if not isinstance(ace, dict):
        return UpdateToastConfig()
    updates = ace.get("updates")
    if not isinstance(updates, dict):
        return UpdateToastConfig()
    return UpdateToastConfig(
        startup_toast=_coerce_bool(updates.get("startup_toast"), default=True),
        post_update_toast=_coerce_bool(updates.get("post_update_toast"), default=True),
        post_update_toast_diffstat=_coerce_bool(
            updates.get("post_update_toast_diffstat"),
            default=True,
        ),
        post_update_toast_commits=_coerce_bool(
            updates.get("post_update_toast_commits"),
            default=True,
        ),
        post_update_toast_max_commits=_coerce_nonnegative_int(
            updates.get("post_update_toast_max_commits"),
            default=_DEFAULT_POST_UPDATE_TOAST_MAX_COMMITS,
        ),
        indicator=_coerce_bool(updates.get("indicator"), default=True),
        check_ttl_seconds=_resolve_check_ttl_seconds(updates),
        recompute_interval_seconds=_resolve_recompute_interval_seconds(updates),
        incoming_commits_enabled=_incoming_commits_enabled(updates),
        startup_toast_max_commits=_coerce_nonnegative_int(
            updates.get("startup_toast_max_commits"),
            default=_DEFAULT_STARTUP_TOAST_MAX_COMMITS,
        ),
    )


def _resolve_check_ttl_seconds(updates: dict[str, Any]) -> float:
    """Resolve the automatic-check cache TTL from the updates config.

    ``check_ttl_minutes`` is the primary knob; ``check_ttl_hours`` is retained
    only for backward compatibility and consulted when minutes is absent. The
    value is carried internally as seconds so the worker never re-derives units.
    """
    minutes = updates.get("check_ttl_minutes")
    if minutes is not None:
        return (
            _coerce_positive_float(minutes, default=_DEFAULT_CHECK_TTL_MINUTES) * 60.0
        )
    hours = updates.get("check_ttl_hours")
    if hours is not None:
        return _coerce_positive_float(hours, default=_DEFAULT_CHECK_TTL_HOURS) * 3600.0
    return DEFAULT_UPDATE_STATUS_TTL_SECONDS


def resolve_check_interval_seconds(updates: dict[str, Any]) -> float:
    """Resolve the positive, finite ACE session check interval in seconds."""
    default_minutes = _AUTOMATIC_UPDATE_CHECK_INTERVAL_SECONDS / 60.0
    minutes = _coerce_strict_positive_finite_float(
        updates.get("check_interval_minutes"),
        default=default_minutes,
    )
    seconds = minutes * 60.0
    if not math.isfinite(seconds) or seconds <= 0:
        return _AUTOMATIC_UPDATE_CHECK_INTERVAL_SECONDS
    return seconds


def _resolve_recompute_interval_seconds(updates: dict[str, Any]) -> float:
    """Resolve the cadence for periodic full network recomputes."""
    minutes = _coerce_strict_positive_finite_float(
        updates.get("recompute_interval_minutes"),
        default=_DEFAULT_RECOMPUTE_INTERVAL_MINUTES,
    )
    seconds = minutes * 60.0
    if not math.isfinite(seconds) or seconds <= 0:
        return _DEFAULT_RECOMPUTE_INTERVAL_SECONDS
    return seconds


def _incoming_commits_enabled(updates: dict[str, Any]) -> bool:
    incoming = updates.get("incoming_commits")
    if not isinstance(incoming, dict):
        return True
    return _coerce_bool(incoming.get("enabled"), default=True)


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


def _coerce_nonnegative_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value if value >= 0 else default
    if isinstance(value, float) and value.is_integer():
        parsed = int(value)
        return parsed if parsed >= 0 else default
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return default
        return parsed if parsed >= 0 else default
    return default


def _coerce_positive_float(value: object, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else default
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return default
        return parsed if parsed >= 0 else default
    return default


def _coerce_strict_positive_finite_float(value: object, *, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    try:
        parsed = float(value)
    except OverflowError:
        return default
    return parsed if math.isfinite(parsed) and parsed > 0 else default
