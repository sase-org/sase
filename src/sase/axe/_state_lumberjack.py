"""Per-lumberjack state directories, PIDs, status, metrics, and logs.

Internal helper module — public API is re-exported through
``sase.axe.state``. Do not import from this module directly.

Paths and shared helpers are looked up through ``sase.axe.state`` at call
time so test patches like ``patch("sase.axe.state.JACK_STATE_DIR", ...)``
propagate to every reader.
"""

import sase.axe.state as _state  # noqa: I001
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class LumberjackStatus:
    """Status of a single lumberjack process."""

    name: str
    pid: int
    started_at: str
    status: Literal["running", "stopped", "error"]
    interval: int
    chops: list[str] = field(default_factory=list)
    last_cycle: str | None = None
    cycles_run: int = 0
    errors_encountered: int = 0
    uptime_seconds: int = 0


@dataclass
class LumberjackMetrics:
    """Cumulative metrics for a single lumberjack process."""

    cycles_run: int = 0
    chops_executed: int = 0
    total_updates: int = 0
    errors_encountered: int = 0


def lumberjack_state_dir(name: str) -> Path:
    """Return the state directory for a given lumberjack.

    Args:
        name: Lumberjack name (e.g. "hooks", "checks").

    Returns:
        Path to ``~/.sase/axe/lumberjacks/{name}/``.
    """
    return _state.JACK_STATE_DIR / name


def ensure_lumberjack_dirs(name: str) -> Path:
    """Create the per-lumberjack state directory tree.

    Creates::

        ~/.sase/axe/lumberjacks/{name}/
        ~/.sase/axe/lumberjacks/{name}/logs/

    Args:
        name: Lumberjack name.

    Returns:
        Path to the lumberjack state directory.
    """
    lumberjack_dir = lumberjack_state_dir(name)
    (lumberjack_dir / "logs").mkdir(parents=True, exist_ok=True)
    return lumberjack_dir


def write_lumberjack_pid(name: str) -> None:
    """Write PID file for a lumberjack process.

    Args:
        name: Lumberjack name.
    """
    lumberjack_dir = ensure_lumberjack_dirs(name)
    (lumberjack_dir / "pid").write_text(str(os.getpid()))


def read_lumberjack_pid(name: str) -> int | None:
    """Read PID for a lumberjack process.

    Args:
        name: Lumberjack name.

    Returns:
        PID as integer, or None if not found.
    """
    pid_file = lumberjack_state_dir(name) / "pid"
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def remove_lumberjack_pid(name: str) -> None:
    """Remove PID file for a lumberjack process.

    Args:
        name: Lumberjack name.
    """
    pid_file = lumberjack_state_dir(name) / "pid"
    try:
        pid_file.unlink()
    except OSError:
        pass


def write_lumberjack_status(status: LumberjackStatus) -> None:
    """Write lumberjack status to disk.

    Args:
        status: Current lumberjack status.
    """
    lumberjack_dir = ensure_lumberjack_dirs(status.name)
    _state.atomic_write_json(lumberjack_dir / "status.json", asdict(status))


def read_lumberjack_status(name: str) -> LumberjackStatus | None:
    """Read lumberjack status from disk.

    Args:
        name: Lumberjack name.

    Returns:
        LumberjackStatus, or None if not available.
    """
    status_file = lumberjack_state_dir(name) / "status.json"
    data = _state.read_json(status_file)
    if data is None:
        return None
    try:
        return LumberjackStatus(**data)
    except TypeError:
        return None


def write_lumberjack_metrics(name: str, metrics: LumberjackMetrics) -> None:
    """Write lumberjack metrics to disk.

    Args:
        name: Lumberjack name.
        metrics: Current metrics.
    """
    lumberjack_dir = ensure_lumberjack_dirs(name)
    _state.atomic_write_json(lumberjack_dir / "metrics.json", asdict(metrics))


def read_lumberjack_metrics(name: str) -> LumberjackMetrics | None:
    """Read lumberjack metrics from disk.

    Args:
        name: Lumberjack name.

    Returns:
        LumberjackMetrics, or None if not available.
    """
    metrics_file = lumberjack_state_dir(name) / "metrics.json"
    data = _state.read_json(metrics_file)
    if data is None:
        return None
    try:
        return LumberjackMetrics(**data)
    except TypeError:
        return None


def write_chop_timestamps(name: str, timestamps: dict[str, str]) -> None:
    """Write chop last-run timestamps to disk.

    Args:
        name: Lumberjack name.
        timestamps: Mapping of chop name to ISO timestamp string.
    """
    lumberjack_dir = ensure_lumberjack_dirs(name)
    _state.atomic_write_json(lumberjack_dir / "chop_timestamps.json", timestamps)


def read_chop_timestamps(name: str) -> dict[str, str]:
    """Read chop last-run timestamps from disk.

    Args:
        name: Lumberjack name.

    Returns:
        Mapping of chop name to ISO timestamp string, or empty dict.
    """
    timestamps_file = lumberjack_state_dir(name) / "chop_timestamps.json"
    data = _state.read_json(timestamps_file)
    if data is None or not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def lumberjack_log_path(name: str) -> Path:
    """Return the output log path for a lumberjack.

    Args:
        name: Lumberjack name.

    Returns:
        Path to ``~/.sase/axe/lumberjacks/{name}/logs/output.log``.
    """
    return lumberjack_state_dir(name) / "logs" / "output.log"


def read_lumberjack_log_tail(name: str, lines: int = 1000) -> str:
    """Read the last N lines of a lumberjack's output log.

    Args:
        name: Lumberjack name.
        lines: Number of lines to read from the end (default: 1000).

    Returns:
        String with the last N lines (ANSI codes preserved).
    """
    log_file = lumberjack_log_path(name)
    if not log_file.exists():
        return ""
    return _state.read_tail_seek(log_file, lines)


def clear_lumberjack_output_log(name: str) -> None:
    """Clear a lumberjack's output log file.

    Args:
        name: Lumberjack name.
    """
    log_file = lumberjack_log_path(name)
    if log_file.exists():
        try:
            log_file.write_text("")
        except OSError:
            pass


def list_lumberjack_names() -> list[str]:
    """List all lumberjack names that have state directories.

    Returns:
        Sorted list of lumberjack names.
    """
    if not _state.JACK_STATE_DIR.exists():
        return []
    return sorted(d.name for d in _state.JACK_STATE_DIR.iterdir() if d.is_dir())


def ensure_shared_dir() -> Path:
    """Create and return the shared state directory.

    Returns:
        Path to ``~/.sase/axe/shared/``.
    """
    _state.SHARED_STATE_DIR.mkdir(parents=True, exist_ok=True)
    return _state.SHARED_STATE_DIR
