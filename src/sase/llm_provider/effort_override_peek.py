"""Lock-free display read for the machine-wide default-effort override.

Keystroke and top-bar paths need the active default-effort override without
paying for the shared Rust lock or the self-cleaning rewrite that
:func:`sase.llm_provider.effort_override.get_active_effort_override`
performs. This module keeps a small, time-gated cache of the parsed state
file and never mutates it.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .effort_override import (
    TemporaryEffortOverride,
    effort_override_state_path,
)

#: Minimum interval between filesystem metadata checks on display-only reads.
_PEEK_STAT_FLOOR_SECONDS = 0.5

_peek_cache_lock = threading.Lock()
_peek_cache_path: Path | None = None
_peek_cache_token: tuple[int, int] | None = None
_peek_cache_deadline = 0.0
_peek_cache_record: TemporaryEffortOverride | None = None


def peek_active_effort_override(
    now: float | None = None,
) -> TemporaryEffortOverride | None:
    """Return the active default-effort override through a display cache.

    This is the display read for keystroke and top-bar paths: it never takes
    the shared state lock and never rewrites, prunes, or deletes the state
    file. The authoritative, self-cleaning read remains
    :func:`sase.llm_provider.effort_override.get_active_effort_override`.

    Filesystem metadata is checked at most once per short monotonic floor. A
    changed ``(mtime_ns, size)`` token reparses the file, while expiry is
    filtered against the requested clock on every call. Missing, unreadable,
    corrupt, or structurally invalid state degrades to no override.
    """
    global _peek_cache_deadline, _peek_cache_record  # noqa: PLW0603
    global _peek_cache_path, _peek_cache_token  # noqa: PLW0603

    current_monotonic = time.monotonic()
    with _peek_cache_lock:
        if current_monotonic < _peek_cache_deadline:
            cached = _peek_cache_record
        else:
            path = effort_override_state_path()
            _peek_cache_deadline = current_monotonic + _PEEK_STAT_FLOOR_SECONDS
            try:
                stat = path.stat()
            except OSError:
                _peek_cache_path = path
                _peek_cache_token = None
                _peek_cache_record = None
                cached = None
            else:
                token = (stat.st_mtime_ns, stat.st_size)
                if path != _peek_cache_path or token != _peek_cache_token:
                    _peek_cache_record = _read_peek_record(path)
                    _peek_cache_path = path
                    _peek_cache_token = token
                cached = _peek_cache_record

    current = time.time() if now is None else now
    if cached is None or not cached.is_active(current):
        return None
    return cached


def _read_peek_record(path: Path) -> TemporaryEffortOverride | None:
    """Parse effort-override state for :func:`peek_active_effort_override`."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return TemporaryEffortOverride.from_wire(data)
    except Exception:  # noqa: BLE001 - display reads always degrade to empty.
        return None


__all__ = ["peek_active_effort_override"]
