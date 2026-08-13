"""Transactional monitor-start coordination primitives."""

from __future__ import annotations

import json
import os
import time
from hashlib import sha256
from pathlib import Path

from sase.core.paths import sase_projects_dir

MONITOR_GO_MARKER = ".monitor_go"
MONITOR_LAUNCH_BARRIER_TIMEOUT_SECONDS = 30.0

#: Marker the supervisor writes once it has taken ownership (dispositions
#: set, meta read, output log opened) to prove it survived its own startup.
MONITOR_STARTED_MARKER = ".monitor_started"
#: Comfortably above the ~0.83s measured startup this guards against a
#: healthy-but-slow start being torn down.
MONITOR_START_ACK_TIMEOUT_SECONDS = 20.0


def monitor_lane_lock_path(project_name: str, lane: str) -> Path:
    """Return the per-project/lane monitor lifecycle lock path."""
    key = sha256(f"{project_name}\0{lane}".encode()).hexdigest()[:32]
    return (
        sase_projects_dir()
        / project_name
        / "artifacts"
        / "ace-run"
        / f".monitor-start-{key}"
    )


def monitor_go_path(artifacts_dir: str | Path) -> Path:
    """Return the marker path that releases a supervisor to exec the command."""
    return Path(artifacts_dir) / MONITOR_GO_MARKER


def monitor_started_path(artifacts_dir: str | Path) -> Path:
    """Return the marker path proving the supervisor took ownership."""
    return Path(artifacts_dir) / MONITOR_STARTED_MARKER


def write_json_marker_atomic(marker_path: Path, payload: dict[str, object]) -> None:
    """Write *payload* as JSON to *marker_path* so a reader never sees a partial file.

    Shared by the ``.monitor_go`` launch barrier and the ``.monitor_started``
    startup acknowledgement: a temp file next to *marker_path*, fsynced, then
    ``os.replace``d into place.
    """
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = marker_path.with_name(
        f".{marker_path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, marker_path)
    except OSError:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


__all__ = [
    "MONITOR_GO_MARKER",
    "MONITOR_LAUNCH_BARRIER_TIMEOUT_SECONDS",
    "MONITOR_STARTED_MARKER",
    "MONITOR_START_ACK_TIMEOUT_SECONDS",
    "monitor_go_path",
    "monitor_lane_lock_path",
    "monitor_started_path",
    "write_json_marker_atomic",
]
