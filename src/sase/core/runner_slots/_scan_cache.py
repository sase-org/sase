"""Host-wide reuse of the runner-slot capacity scan.

Waiters hold ``runner_slots.lock`` while calling this: a fresh cache entry
matching the current slot-state token is reused instead of walking artifacts
again. Claims still run against that lock-validated snapshot.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    agent_artifact_records_from_dicts,
    agent_scan_wire_to_json_dict,
)
from sase.core.paths import sase_home
from sase.core.runner_slots._signal import runner_slot_state_token

_CACHE_NAME = "runner_slots.scan.json"
_STALE_TEMP_SECONDS = 60 * 60


@dataclass(frozen=True)
class _ParsedScanCacheEntry:
    """In-process reuse of the last parsed slot-scan payload.

    The feed tick reads the scan cache every 10 s. Re-parsing the JSON on
    every tick is wasteful while the file is unchanged, so a parsed entry is
    reused while the file's ``(mtime_ns, size)`` still matches. Identical
    file bytes imply an identical token, so no separate token comparison is
    needed on the hit path.
    """

    path: str
    mtime_ns: int
    size: int
    token: str
    scanned_at: float
    records: tuple[AgentArtifactRecordWire, ...]


_parsed_scan_cache: _ParsedScanCacheEntry | None = None
_parsed_scan_cache_lock = threading.Lock()


@dataclass(frozen=True)
class RunnerSlotScanCache:
    """One host-wide capacity-scan cache entry, including a stale token."""

    token: str
    scanned_at: float
    records: tuple[AgentArtifactRecordWire, ...]


def _runner_slot_scan_cache_path() -> Path:
    """Return the host-wide capacity-scan cache path under ``SASE_HOME``."""
    return sase_home() / _CACHE_NAME


def read_runner_slot_scan_cache() -> RunnerSlotScanCache | None:
    """Return the cached scan even when its token no longer matches live state.

    Display readers need the stale entry so a token change inside the
    rate-limit window can still serve records with ``scan_current=False``.
    """
    cached = _read_scan_cache()
    if cached is None:
        return None
    return RunnerSlotScanCache(
        token=cached["token"],
        scanned_at=cached["scanned_at"],
        records=tuple(cached["records"]),
    )


def load_or_refresh_runner_slot_scan(
    collect: Callable[[], list[AgentArtifactRecordWire]],
    *,
    max_age: float,
    now: float | None = None,
    token: str | None = None,
) -> list[AgentArtifactRecordWire]:
    """Return cached capacity records, scanning only when the entry is stale.

    An entry is reusable when its stored token matches *token* (default: the
    live slot-state token) and ``now - scanned_at`` is strictly less than
    *max_age*.
    """
    current_token = runner_slot_state_token() if token is None else token
    timestamp = time.time() if now is None else now
    cached = _read_scan_cache()
    if (
        cached is not None
        and cached["token"] == current_token
        and timestamp - cached["scanned_at"] < max_age
    ):
        return cached["records"]
    records = collect()
    _write_scan_cache(current_token, timestamp, records)
    return records


def _parsed_scan_cache_hit(
    path: Path,
    stat: os.stat_result,
) -> dict[str, Any] | None:
    """Return the memoized parse when the file bytes cannot have changed."""
    with _parsed_scan_cache_lock:
        entry = _parsed_scan_cache
    if (
        entry is None
        or entry.path != str(path)
        or entry.mtime_ns != stat.st_mtime_ns
        or entry.size != stat.st_size
    ):
        return None
    return {
        "token": entry.token,
        "scanned_at": entry.scanned_at,
        "records": list(entry.records),
    }


def _store_parsed_scan_cache(entry: _ParsedScanCacheEntry) -> None:
    global _parsed_scan_cache
    with _parsed_scan_cache_lock:
        _parsed_scan_cache = entry


def _invalidate_parsed_scan_cache(path: Path) -> None:
    global _parsed_scan_cache
    with _parsed_scan_cache_lock:
        if _parsed_scan_cache is not None and _parsed_scan_cache.path == str(path):
            _parsed_scan_cache = None


def _read_scan_cache() -> dict[str, Any] | None:
    path = _runner_slot_scan_cache_path()
    try:
        stat = path.stat()
    except OSError:
        _invalidate_parsed_scan_cache(path)
        return None
    hit = _parsed_scan_cache_hit(path, stat)
    if hit is not None:
        return hit
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        _invalidate_parsed_scan_cache(path)
        return None
    if not isinstance(payload, dict):
        _invalidate_parsed_scan_cache(path)
        return None
    token = payload.get("token")
    scanned_at = payload.get("scanned_at")
    raw_records = payload.get("records")
    if not isinstance(token, str) or not isinstance(scanned_at, (int, float)):
        _invalidate_parsed_scan_cache(path)
        return None
    if isinstance(scanned_at, bool) or not isinstance(raw_records, list):
        _invalidate_parsed_scan_cache(path)
        return None
    try:
        records = agent_artifact_records_from_dicts(
            [record for record in raw_records if isinstance(record, dict)]
        )
    except (KeyError, TypeError, ValueError):
        _invalidate_parsed_scan_cache(path)
        return None
    if len(records) != len(raw_records):
        _invalidate_parsed_scan_cache(path)
        return None
    _store_parsed_scan_cache(
        _ParsedScanCacheEntry(
            path=str(path),
            mtime_ns=stat.st_mtime_ns,
            size=stat.st_size,
            token=token,
            scanned_at=float(scanned_at),
            records=tuple(records),
        )
    )
    return {"token": token, "scanned_at": float(scanned_at), "records": records}


def _write_scan_cache(
    token: str,
    scanned_at: float,
    records: list[AgentArtifactRecordWire],
) -> None:
    path = _runner_slot_scan_cache_path()
    _prune_stale_scan_cache_temps(path, time.time())
    payload = {
        "token": token,
        "scanned_at": scanned_at,
        "records": agent_scan_wire_to_json_dict(records),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
    except OSError:
        return
    tmp_path = Path(tmp_name)
    replaced = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
        os.replace(tmp_path, path)
        replaced = True
    except (OSError, TypeError, ValueError):
        return
    finally:
        if not replaced:
            try:
                tmp_path.unlink()
            except OSError:
                pass
    try:
        stat = path.stat()
    except OSError:
        return
    _store_parsed_scan_cache(
        _ParsedScanCacheEntry(
            path=str(path),
            mtime_ns=stat.st_mtime_ns,
            size=stat.st_size,
            token=token,
            scanned_at=scanned_at,
            records=tuple(records),
        )
    )


def _prune_stale_scan_cache_temps(path: Path, now: float) -> None:
    """Best-effort remove abandoned sibling temp files older than one hour."""
    try:
        for candidate in path.parent.glob(f".{path.name}.*.tmp"):
            try:
                if now - candidate.stat().st_mtime > _STALE_TEMP_SECONDS:
                    candidate.unlink()
            except OSError:
                continue
    except OSError:
        pass


__all__ = [
    "RunnerSlotScanCache",
    "load_or_refresh_runner_slot_scan",
    "read_runner_slot_scan_cache",
]
