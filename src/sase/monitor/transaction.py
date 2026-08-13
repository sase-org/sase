"""Transactional monitor-start coordination primitives."""

from __future__ import annotations

from pathlib import Path

MONITOR_GO_MARKER = ".monitor_go"
MONITOR_LAUNCH_BARRIER_TIMEOUT_SECONDS = 30.0


def monitor_go_path(artifacts_dir: str | Path) -> Path:
    """Return the marker path that releases a supervisor to exec the command."""
    return Path(artifacts_dir) / MONITOR_GO_MARKER


__all__ = [
    "MONITOR_GO_MARKER",
    "MONITOR_LAUNCH_BARRIER_TIMEOUT_SECONDS",
    "monitor_go_path",
]
