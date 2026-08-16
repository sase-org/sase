"""Cheap, lock-free change-detection token for the no-``%model`` launch default.

The launch default can move without any state this repo owns directly
changing: a config edit to ``llm_provider.default_model`` or an alias
definition, a load-balanced pool's rotation cursor advancing, a temporary
override being set on the default-launch setting, or a provider disable
changing which pool members are available. Re-resolving the effective default
on every timer tick would mean taking the pool-rotation lock and performing a
self-cleaning override read from a Textual timer callback, which
``sase/memory/tui_perf.md`` forbids. This module instead answers a much
cheaper question — "might the launch default have changed since the last
resolve?" — using only ``os.stat`` and the already time-gated
:func:`sase.config.core.current_config_token`, so a caller can revalidate
every tick and only pay for the real resolve when the token actually changes.

**Known, accepted limitation:** an ``(mtime_ns, size)`` token can in principle
miss a rewrite that lands in the same nanosecond at the same size. Every state
file this token watches is written through ``os.replace`` of a freshly
written temp file, so a same-nanosecond, same-size collision is not
realistically reachable in practice.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from sase.config.core import current_config_token

from .load_balancing import rotation_state_path
from .provider_disable_peek import provider_disable_state_path
from .temporary_override_state import state_path as temporary_override_state_path

#: Minimum interval between filesystem metadata checks on display-only reads.
_PEEK_STAT_FLOOR_SECONDS = 0.5

#: Returned when a stat (other than a missing file) or the config token lookup
#: raises unexpectedly, so a broken read degrades to "no change detected"
#: rather than causing a refresh storm.
_TOKEN_ERROR_SENTINEL: tuple[object, ...] = ("launch-default-peek-error",)

_token_cache_lock = threading.Lock()
_token_cache_deadline = 0.0
_token_cache_value: tuple[object, ...] = ()


def peek_launch_default_change_token() -> tuple[object, ...]:
    """Return a cheap token that changes when the launch default might have.

    Built from, in order: the current config token (covers
    ``llm_provider.default_model`` and alias-definition edits), the
    load-balanced pool rotation state file, the temporary-override state
    file, and the provider-disable state file. Filesystem metadata is
    checked at most once per short monotonic floor. Reads are ``os.stat``
    only — no parsing, no locks.
    """
    global _token_cache_deadline, _token_cache_value  # noqa: PLW0603

    current_monotonic = time.monotonic()
    with _token_cache_lock:
        if current_monotonic < _token_cache_deadline:
            return _token_cache_value

        _token_cache_deadline = current_monotonic + _PEEK_STAT_FLOOR_SECONDS
        token: tuple[object, ...]
        try:
            token = (
                current_config_token(),
                _stat_token(rotation_state_path()),
                _stat_token(temporary_override_state_path()),
                _stat_token(provider_disable_state_path()),
            )
        except Exception:  # noqa: BLE001 - display reads always degrade.
            token = _TOKEN_ERROR_SENTINEL
        _token_cache_value = token
        return token


def _stat_token(path: Path) -> tuple[int, int] | None:
    """Return ``(mtime_ns, size)`` for *path*, or ``None`` when missing."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


__all__ = ["peek_launch_default_change_token"]
