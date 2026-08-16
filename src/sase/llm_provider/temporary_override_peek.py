"""Lock-free display read for temporary, per-alias LLM provider/model overrides.

Keystroke paths (completion menus, indicators) need the active overrides without
paying for the shared state lock or the self-cleaning rewrite that
:func:`sase.llm_provider.temporary_override_state.load_active_overrides`
performs. This module keeps a small, time-gated cache of the parsed state file
and never mutates it.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .model_launch_settings import (
    DEFAULT_MODEL_FIELD,
    launch_model_setting_override_key,
)
from .temporary_override_state import (
    TemporaryLLMOverride,
    entry_from_dict,
    extract_raw_entries,
    state_path,
)

#: Minimum interval between filesystem metadata checks on display-only reads.
_PEEK_STAT_FLOOR_SECONDS = 0.5

_peek_cache_lock = threading.Lock()
_peek_cache_path: Path | None = None
_peek_cache_token: tuple[int, int] | None = None
_peek_cache_deadline = 0.0
_peek_cache_entries: dict[str, TemporaryLLMOverride] = {}


def peek_active_alias_overrides(
    now: float | None = None,
) -> dict[str, TemporaryLLMOverride]:
    """Return active overrides through a read-only, time-gated display cache.

    This is the display read for keystroke paths: it never takes the shared
    state lock and never rewrites, prunes, or deletes the state file. The
    authoritative, self-cleaning read for Models-panel and launch paths remains
    :func:`sase.llm_provider.temporary_override.get_active_alias_overrides`.

    Filesystem metadata is checked at most once per short monotonic floor. A
    changed ``(mtime_ns, size)`` token reparses the file, while expiry is
    filtered against the requested clock on every call. Missing, unreadable,
    corrupt, or structurally invalid state degrades to an empty mapping.
    """
    global _peek_cache_deadline, _peek_cache_entries  # noqa: PLW0603
    global _peek_cache_path, _peek_cache_token  # noqa: PLW0603

    current_monotonic = time.monotonic()
    with _peek_cache_lock:
        if current_monotonic < _peek_cache_deadline:
            cached = dict(_peek_cache_entries)
        else:
            path = state_path()
            _peek_cache_deadline = current_monotonic + _PEEK_STAT_FLOOR_SECONDS
            try:
                stat = path.stat()
            except OSError:
                _peek_cache_path = path
                _peek_cache_token = None
                _peek_cache_entries = {}
                cached = {}
            else:
                token = (stat.st_mtime_ns, stat.st_size)
                if path != _peek_cache_path or token != _peek_cache_token:
                    _peek_cache_entries = _read_peek_entries(path)
                    _peek_cache_path = path
                    _peek_cache_token = token
                cached = dict(_peek_cache_entries)

    current = time.time() if now is None else now
    return {
        alias: override
        for alias, override in cached.items()
        if override.expires_at is None or current < override.expires_at
    }


def peek_active_temporary_override(
    now: float | None = None,
) -> TemporaryLLMOverride | None:
    """Return the active default-launch override through the display cache.

    Lock-free counterpart of
    :func:`sase.llm_provider.temporary_override.get_active_temporary_override`,
    for keystroke and top-bar paths that must not take the shared state lock.
    """
    return peek_active_alias_overrides(now).get(
        launch_model_setting_override_key(DEFAULT_MODEL_FIELD)
    )


def _read_peek_entries(path: Path) -> dict[str, TemporaryLLMOverride]:
    """Parse override state for :func:`peek_active_alias_overrides`."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        raw_entries, _ = extract_raw_entries(data)
        if raw_entries is None:
            return {}
        return {
            alias: override
            for alias, entry in raw_entries.items()
            if (override := entry_from_dict(entry)) is not None
        }
    except Exception:  # noqa: BLE001 - display reads always degrade to empty.
        return {}
