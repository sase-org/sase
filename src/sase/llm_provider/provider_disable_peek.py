"""Lock-free display read for temporary LLM provider disables."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from sase.core.paths import sase_home

from .provider_disable import (
    PROVIDER_DISABLE_MODE_HARD,
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)

_PROVIDER_DISABLE_WIRE_SCHEMA_V1 = 1

_STATE_FILENAME = "llm_provider_disables.json"

#: Minimum interval between filesystem metadata checks on display-only reads.
_PEEK_STAT_FLOOR_SECONDS = 0.5

_peek_cache_lock = threading.Lock()
_peek_cache_path: Path | None = None
_peek_cache_token: tuple[int, int] | None = None
_peek_cache_deadline = 0.0
_peek_cache_entries: dict[str, TemporaryProviderDisable] = {}


def peek_active_provider_disables(
    now: float | None = None,
) -> dict[str, TemporaryProviderDisable]:
    """Return active provider disables through a read-only display cache.

    This is the display read for keystroke and top-bar paths: it never takes
    the shared state lock and never rewrites, prunes, or deletes the state
    file. The authoritative read remains
    :func:`sase.llm_provider.provider_disable.get_active_provider_disables`.

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
            path = provider_disable_state_path()
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
        provider: record
        for provider, record in cached.items()
        if record.expires_at is None or current < record.expires_at
    }


def provider_disable_state_path() -> Path:
    return sase_home() / _STATE_FILENAME


def _read_peek_entries(path: Path) -> dict[str, TemporaryProviderDisable]:
    """Parse provider-disable state for :func:`peek_active_provider_disables`."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"version", "disables"}:
            return {}
        version = data["version"]
        if version not in {
            _PROVIDER_DISABLE_WIRE_SCHEMA_V1,
            PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        }:
            return {}
        raw_entries = data["disables"]
        if not isinstance(raw_entries, dict):
            return {}
        default_hard = version == _PROVIDER_DISABLE_WIRE_SCHEMA_V1
        records: dict[str, TemporaryProviderDisable] = {}
        for provider in sorted(raw_entries):
            record = _peek_record(raw_entries[provider], default_hard=default_hard)
            if record.provider != provider:
                return {}
            records[provider] = record
        return records
    except Exception:  # noqa: BLE001 - display reads always degrade to empty.
        return {}


def _peek_record(payload: object, *, default_hard: bool) -> TemporaryProviderDisable:
    """Rehydrate one peek record, mapping leftover v1 files to hard disables."""
    if default_hard and isinstance(payload, dict):
        payload = {
            **payload,
            "version": PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
            "mode": PROVIDER_DISABLE_MODE_HARD,
        }
    return TemporaryProviderDisable.from_wire(payload)


__all__ = ["peek_active_provider_disables", "provider_disable_state_path"]
