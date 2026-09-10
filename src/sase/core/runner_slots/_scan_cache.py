"""Host-wide reuse of the runner-slot capacity scan.

Waiters hold ``runner_slots.lock`` while calling this: a fresh cache entry
matching the current slot-state token is reused instead of walking artifacts
again. Claims still run against that lock-validated snapshot.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable
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


def _runner_slot_scan_cache_path() -> Path:
    """Return the host-wide capacity-scan cache path under ``SASE_HOME``."""
    return sase_home() / _CACHE_NAME


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


def _read_scan_cache() -> dict[str, Any] | None:
    path = _runner_slot_scan_cache_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None
    token = payload.get("token")
    scanned_at = payload.get("scanned_at")
    raw_records = payload.get("records")
    if not isinstance(token, str) or not isinstance(scanned_at, (int, float)):
        return None
    if isinstance(scanned_at, bool) or not isinstance(raw_records, list):
        return None
    try:
        records = agent_artifact_records_from_dicts(
            [record for record in raw_records if isinstance(record, dict)]
        )
    except (KeyError, TypeError, ValueError):
        return None
    if len(records) != len(raw_records):
        return None
    return {"token": token, "scanned_at": float(scanned_at), "records": records}


def _write_scan_cache(
    token: str,
    scanned_at: float,
    records: list[AgentArtifactRecordWire],
) -> None:
    path = _runner_slot_scan_cache_path()
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


__all__ = [
    "load_or_refresh_runner_slot_scan",
]
