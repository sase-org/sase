"""Bounded durable output logs for monitor family members."""

from __future__ import annotations

from pathlib import Path

from sase.axe.state import read_tail_seek
from sase.logs._bounded import (
    DEFAULT_MAX_BYTES,
    append_bytes_locked,
    log_file_lock,
    max_bytes_from_env,
)

ENV_MAX_BYTES = "SASE_MONITOR_LOG_MAX_BYTES"
MONITOR_LOG_FILENAME = "live_reply.md"
DEFAULT_MONITOR_LOG_MAX_BYTES = DEFAULT_MAX_BYTES


def monitor_log_path(artifacts_dir: str | Path) -> Path:
    """Return the active combined-output log path for one monitor."""
    return Path(artifacts_dir) / MONITOR_LOG_FILENAME


def monitor_log_max_bytes() -> int:
    """Return the monitor log byte cap, honoring the environment override."""
    return max_bytes_from_env(ENV_MAX_BYTES, DEFAULT_MONITOR_LOG_MAX_BYTES)


def append_monitor_log_bytes(path: Path, chunk: bytes) -> None:
    """Append *chunk* through the monitor bounded-log contract."""
    if not chunk:
        return
    with log_file_lock(path):
        append_bytes_locked(
            path,
            chunk,
            max_bytes=monitor_log_max_bytes(),
            truncate_oversized=True,
        )


def read_monitor_log_tail(path: Path, lines: int) -> str:
    """Return the newest *lines* retained across active and rotated logs."""
    if lines <= 0:
        return ""
    rotated = path.with_name(f"{path.name}.1")
    prior = read_tail_seek(rotated, lines)
    current = read_tail_seek(path, lines)
    retained = "".join((prior, current)).splitlines(keepends=True)[-lines:]
    return "".join(retained)


__all__ = [
    "DEFAULT_MONITOR_LOG_MAX_BYTES",
    "ENV_MAX_BYTES",
    "MONITOR_LOG_FILENAME",
    "append_monitor_log_bytes",
    "monitor_log_max_bytes",
    "monitor_log_path",
    "read_monitor_log_tail",
]
