"""Lock-free display reads for temporary LLM provider priority."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from .provider_disable import TemporaryProviderDisable
from .provider_disable_peek import peek_active_provider_disables
from .provider_priority import (
    ProviderPriorityDecode,
    ProviderRoutingContext,
    TemporaryProviderPriority,
    decode_provider_priority,
    provider_priority_route_key,
    provider_priority_state_path,
    provider_routing_context_from_parts,
)

#: Minimum interval between filesystem metadata checks on display-only reads.
_PEEK_STAT_FLOOR_SECONDS = 0.5

_peek_cache_lock = threading.Lock()
_peek_cache_path: Path | None = None
_peek_cache_token: tuple[int, int] | None = None
_peek_cache_deadline = 0.0
_peek_cache_decode = ProviderPriorityDecode(version=1, priority=None, diagnostics=())


def peek_active_provider_priority(
    now: float | None = None,
) -> TemporaryProviderPriority | None:
    """Return active priority through a read-only display cache.

    This never takes the shared routing-state lock and never rewrites or
    prunes the priority file. A changed ``(mtime_ns, size)`` token reparses
    the file, while expiry is filtered against the requested clock on every
    call so priority-only routing can restore without a file rewrite.
    """
    current = time.time() if now is None else now
    priority = peek_provider_priority_decode(current).priority
    if priority is None or not priority.is_active(current):
        return None
    return priority


def peek_provider_priority_decode(now: float | None = None) -> ProviderPriorityDecode:
    """Return cached lock-free priority decode diagnostics and active record."""
    global _peek_cache_deadline, _peek_cache_decode  # noqa: PLW0603
    global _peek_cache_path, _peek_cache_token  # noqa: PLW0603

    current_monotonic = time.monotonic()
    with _peek_cache_lock:
        if current_monotonic < _peek_cache_deadline:
            cached = _peek_cache_decode
        else:
            path = provider_priority_state_path()
            _peek_cache_deadline = current_monotonic + _PEEK_STAT_FLOOR_SECONDS
            try:
                stat = path.stat()
            except OSError:
                _peek_cache_path = path
                _peek_cache_token = None
                _peek_cache_decode = ProviderPriorityDecode(
                    version=1,
                    priority=None,
                    diagnostics=(),
                )
                cached = _peek_cache_decode
            else:
                token = (stat.st_mtime_ns, stat.st_size)
                if path != _peek_cache_path or token != _peek_cache_token:
                    _peek_cache_decode = _read_priority_decode(path, now)
                    _peek_cache_path = path
                    _peek_cache_token = token
                cached = _peek_cache_decode

    current = time.time() if now is None else now
    priority = cached.priority
    if priority is None or not priority.is_active(current):
        priority = None
    return ProviderPriorityDecode(
        version=cached.version,
        priority=priority,
        diagnostics=cached.diagnostics,
    )


def peek_provider_routing_context(
    now: float | None = None,
    *,
    provider_disables: dict[str, TemporaryProviderDisable] | None = None,
) -> ProviderRoutingContext:
    """Return a lock-free display routing context from cached components."""
    current = time.time() if now is None else now
    disables = (
        peek_active_provider_disables(current)
        if provider_disables is None
        else provider_disables
    )
    return provider_routing_context_from_parts(
        disables,
        peek_active_provider_priority(current),
        captured_at=current if provider_disables is None or now is not None else None,
    )


def peek_provider_priority_change_token(
    now: float | None = None,
) -> tuple[tuple[int, int] | None, tuple[object, ...] | None]:
    """Return a display token that changes on priority writes and expiry."""
    path = provider_priority_state_path()
    try:
        stat = path.stat()
    except OSError:
        state_token = None
    else:
        state_token = (stat.st_mtime_ns, stat.st_size)
    return state_token, provider_priority_route_key(peek_active_provider_priority(now))


def _read_priority_decode(
    path: Path,
    now: float | None,
) -> ProviderPriorityDecode:
    """Decode priority state for :func:`peek_active_provider_priority`."""
    try:
        return decode_provider_priority(path.read_bytes(), now=now)
    except Exception as exc:  # noqa: BLE001 - display reads preserve responsiveness.
        return ProviderPriorityDecode(
            version=1,
            priority=None,
            diagnostics=(f"provider priority state is unreadable: {exc}",),
        )


__all__ = [
    "peek_active_provider_priority",
    "peek_provider_priority_change_token",
    "peek_provider_priority_decode",
    "peek_provider_routing_context",
    "provider_priority_state_path",
]
