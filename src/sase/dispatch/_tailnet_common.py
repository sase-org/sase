"""Shared helpers for built-in tailnet discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_TAILSCALE_STATUS_MAX_BYTES = 1024 * 1024
_TAILSCALE_STDERR_MAX_BYTES = 16 * 1024
_TAILNET_HEALTH_MAX_BYTES = 64 * 1024
_TAILNET_HEALTH_PATH = "/api/v1/health"
_TAILNET_DEFAULT_PROBE_TIMEOUT_SECONDS = 1.0
_TAILNET_MIN_TIMEOUT_SECONDS = 0.001


def unique_strings(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def config_positive_float(
    config: Mapping[str, Any],
    key: str,
    default: float,
) -> float:
    value = config.get(key)
    if value is None or isinstance(value, bool):
        return default
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return default
    return candidate if candidate > 0 else default


def config_positive_int(
    config: Mapping[str, Any],
    key: str,
    default: int,
) -> int:
    value = config.get(key)
    if value is None or isinstance(value, bool):
        return default
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        return default
    return candidate if candidate > 0 else default


def positive_timeout(value: float) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = _TAILNET_MIN_TIMEOUT_SECONDS
    return max(_TAILNET_MIN_TIMEOUT_SECONDS, timeout)


def safe_text(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")
