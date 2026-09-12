"""Transactional monitor-start coordination primitives."""

from __future__ import annotations

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


__all__ = [
    "MONITOR_GO_MARKER",
    "MONITOR_LAUNCH_BARRIER_TIMEOUT_SECONDS",
    "MONITOR_STARTED_MARKER",
    "MONITOR_START_ACK_TIMEOUT_SECONDS",
    "monitor_go_path",
    "monitor_lane_lock_path",
    "monitor_started_path",
]
