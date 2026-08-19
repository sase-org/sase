"""Progress heartbeats: the evidence that a grant is still doing work.

Split out of :mod:`tests._suite_gate`. A holder proves it is alive by writing
a sidecar file next to its tokens; :mod:`tests._suite_gate_holders` reads that
sidecar back when it judges whether a grant has gone stale. The sidecar exists
because a nested pytest child cannot adopt its parent's flock but *is* still
progress, so it needs somewhere to say so.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


_PROGRESS_WRITE_INTERVAL_SECONDS = 5.0
#: Last sidecar write per lease, so a fast suite does not write one file per
#: test. Keyed by lease id because a nested child shares its parent's.
_progress_last_write: dict[str, float] = {}
_progress_counts: dict[str, int] = {}


def should_record_progress(lease_id: str, event: str, now: float) -> int | None:
    """Return the lease's next progress count, or ``None`` if throttled.

    Per-test ``call`` events are rate-limited to one sidecar write every
    :data:`_PROGRESS_WRITE_INTERVAL_SECONDS`; anything else — session start,
    collection — always counts, because those are the events that prove a slow
    run is still moving before the first test finishes.
    """
    last = _progress_last_write.get(lease_id, 0.0)
    if event == "call" and now - last < _PROGRESS_WRITE_INTERVAL_SECONDS:
        return None
    progress = _progress_counts.get(lease_id, 0) + 1
    _progress_counts[lease_id] = progress
    _progress_last_write[lease_id] = now
    return progress


def _progress_sidecar_path(directory: Path, lease_id: str) -> Path:
    return directory / f"lease-{lease_id}.progress"


def write_progress_sidecar(
    directory: Path,
    lease_id: str,
    *,
    heartbeat: float,
    progress: int,
    event: str,
) -> None:
    """Atomically publish this lease's latest heartbeat beside its tokens."""
    directory.mkdir(parents=True, exist_ok=True)
    path = _progress_sidecar_path(directory, lease_id)
    payload = {
        "event": event,
        "heartbeat": heartbeat,
        "lease_id": lease_id,
        "progress": progress,
    }
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(
            json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
        )
        tmp_path.replace(path)
    except OSError:
        tmp_path.unlink(missing_ok=True)


def read_progress_sidecar(directory: Path, lease_id: str) -> dict[str, Any] | None:
    """Return the lease's published ``heartbeat``/``progress``, if any."""
    path = _progress_sidecar_path(directory, lease_id)
    try:
        parsed: Any = json.loads(path.read_text(encoding="utf-8"))
        heartbeat = float(parsed["heartbeat"])
        progress = int(parsed.get("progress", 0))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return {"heartbeat": heartbeat, "progress": progress}


def remove_progress_sidecar(directory: Path, lease_id: str) -> None:
    """Drop the lease's sidecar and the in-process throttle state behind it."""
    path = _progress_sidecar_path(directory, lease_id)
    try:
        path.unlink()
    except OSError:
        pass
    _progress_last_write.pop(lease_id, None)
    _progress_counts.pop(lease_id, None)
