"""Hashable capacity-report signatures for TUI auto-refresh."""

from __future__ import annotations

from typing import Any

CAPACITY_REPORT_POLL_SECONDS = 10.0


def freeze_capacity_value(value: Any) -> Any:
    """Freeze capacity inputs/outputs into hashable, value-based material."""
    if isinstance(value, dict):
        return tuple(
            sorted(
                (str(key), freeze_capacity_value(item)) for key, item in value.items()
            )
        )
    if isinstance(value, (tuple, list)):
        return tuple(freeze_capacity_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((freeze_capacity_value(item) for item in value), key=repr))
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    return repr(value)


def capacity_override_fingerprint(
    configured_limit: Any,
    override: Any,
) -> Any:
    """Fingerprint override state without computation timestamps.

    Includes configured limit, override identity/limit/expiry/source and the
    derived effective limit. Excludes ``captured_at`` which changes on every
    build.
    """
    if override is None:
        return (configured_limit, None, configured_limit)
    # ``EffectiveRunnerLimitSnapshot.effective_limit(now)`` needs ``now``;
    # recompute deterministically from override state instead.
    effective_value = configured_limit
    try:
        import time as _time

        now_wall = _time.time()
        if hasattr(override, "active_override"):
            # Snapshot-shaped object; resolve via its own helper when present.
            active = override.active_override(now_wall)
            if active is None:
                effective_value = configured_limit
            else:
                effective_value = getattr(active, "limit", configured_limit)
        elif hasattr(override, "is_active"):
            active = bool(override.is_active(now_wall))
            limit = getattr(override, "limit", configured_limit)
            effective_value = limit if active else configured_limit
        elif hasattr(override, "limit"):
            # Bare override record without activity helper; treat as active
            # only when its expiry (when present) has not passed.
            expires_at = getattr(override, "expires_at", None)
            if isinstance(expires_at, (int, float)) and now_wall >= float(expires_at):
                effective_value = configured_limit
            else:
                effective_value = override.limit
    except Exception:
        pass
    return (
        configured_limit,
        (
            getattr(override, "version", None),
            getattr(override, "limit", None),
            getattr(override, "expires_at", None),
            getattr(override, "source", None),
        ),
        effective_value,
    )
