"""Disk state management for sase axe scheduler.

This module handles all state persistence for the axe scheduler, enabling
sase ace to monitor and control axe processes via the TUI.

Includes both the flat scheduler state (legacy) and per-lumberjack state
directories used by the new lumberjack architecture.
"""

import json
import os
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from sase.sase_utils import EASTERN_TZ

# State directory location
AXE_STATE_DIR = Path.home() / ".sase" / "axe"

# Per-lumberjack state lives under this subdirectory
LUMBERJACK_STATE_DIR = AXE_STATE_DIR / "lumberjacks"

# Shared cross-process state
SHARED_STATE_DIR = AXE_STATE_DIR / "shared"


@dataclass
class AxeStatus:
    """Current status of the axe scheduler for TUI display."""

    pid: int
    started_at: str
    status: Literal["running", "stopped", "error"]
    full_check_interval: int
    hook_interval: int
    max_runners: int
    query: str
    zombie_timeout: int
    current_runners: int
    last_full_cycle: str | None
    last_hook_cycle: str | None
    next_full_cycle: str | None
    total_changespecs: int
    filtered_changespecs: int
    uptime_seconds: int


@dataclass
class CycleResult:
    """Result of a scheduler cycle for logging/debugging."""

    timestamp: str
    cycle_type: Literal["full", "hook", "comment"]
    duration_ms: int
    changespecs_processed: int
    updates: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class AxeMetrics:
    """Performance metrics for the axe scheduler."""

    full_cycles_run: int = 0
    hook_cycles_run: int = 0
    total_updates: int = 0
    hooks_started: int = 0
    hooks_completed: int = 0
    mentors_started: int = 0
    mentors_completed: int = 0
    workflows_started: int = 0
    workflows_completed: int = 0
    zombies_detected: int = 0
    stale_running_cleaned: int = 0
    errors_encountered: int = 0


def _ensure_state_dir() -> None:
    """Ensure state directory exists."""
    AXE_STATE_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, data: dict | list) -> None:
    """Write JSON atomically using temp file + rename.

    Args:
        path: Target file path.
        data: Dictionary or list to write as JSON.
    """
    _ensure_state_dir()
    temp_path = path.with_suffix(".tmp")
    try:
        with open(temp_path, "w") as f:
            json.dump(data, f, indent=2)
        temp_path.rename(path)
    except OSError:
        # Clean up temp file if rename failed
        try:
            temp_path.unlink()
        except OSError:
            pass


def _read_json(path: Path) -> dict | None:
    """Read JSON file safely.

    Args:
        path: File path to read.

    Returns:
        Parsed JSON dict, or None if file doesn't exist or is invalid.
    """
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


# --- PID File ---


def read_pid_file() -> int | None:
    """Read PID from file.

    Returns:
        PID as integer, or None if file doesn't exist or is invalid.
    """
    pid_file = AXE_STATE_DIR / "pid"
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def remove_pid_file() -> None:
    """Remove PID file on shutdown."""
    pid_file = AXE_STATE_DIR / "pid"
    try:
        pid_file.unlink()
    except OSError:
        pass


# --- Status ---


def read_status() -> AxeStatus | None:
    """Read current status from disk.

    Returns:
        AxeStatus object, or None if file doesn't exist or is invalid.
    """
    status_file = AXE_STATE_DIR / "status.json"
    data = _read_json(status_file)
    if data is None:
        return None
    try:
        return AxeStatus(**data)
    except TypeError:
        return None


# --- Cycle Results ---


def write_cycle_result(result: CycleResult) -> None:
    """Write cycle result to disk for debugging.

    Args:
        result: Result of the completed cycle.
    """
    filename = f"last_{result.cycle_type}_cycle.json"
    result_file = AXE_STATE_DIR / filename
    _atomic_write_json(result_file, asdict(result))


def read_cycle_result(
    cycle_type: Literal["full", "hook", "comment"],
) -> CycleResult | None:
    """Read last cycle result from disk.

    Args:
        cycle_type: Type of cycle to read ("full", "hook", or "comment").

    Returns:
        CycleResult object, or None if file doesn't exist or is invalid.
    """
    filename = f"last_{cycle_type}_cycle.json"
    result_file = AXE_STATE_DIR / filename
    data = _read_json(result_file)
    if data is None:
        return None
    try:
        return CycleResult(**data)
    except TypeError:
        return None


# --- Metrics ---


def read_metrics() -> AxeMetrics | None:
    """Read metrics from disk.

    Returns:
        AxeMetrics object, or None if file doesn't exist or is invalid.
    """
    metrics_file = AXE_STATE_DIR / "metrics.json"
    data = _read_json(metrics_file)
    if data is None:
        return None
    try:
        return AxeMetrics(**data)
    except TypeError:
        return None


# --- Errors ---


def append_error(error_info: dict) -> None:
    """Append error to recent errors list.

    Keeps only the last 100 errors.

    Args:
        error_info: Dictionary with error details (timestamp, job, error, traceback).
    """
    errors_file = AXE_STATE_DIR / "recent_errors.json"
    errors: list[dict] = _read_json(errors_file) or []  # type: ignore[assignment]
    if not isinstance(errors, list):
        errors = []

    errors.append(error_info)
    # Keep only last 100 errors
    errors = errors[-100:]

    _atomic_write_json(errors_file, errors)


def read_errors() -> list[dict]:
    """Read recent errors from disk.

    Returns:
        List of error dictionaries, or empty list if none.
    """
    errors_file = AXE_STATE_DIR / "recent_errors.json"
    errors = _read_json(errors_file)
    if errors is None or not isinstance(errors, list):
        return []
    return errors


# --- Output Log ---


# Path to the output log file with ANSI codes
AXE_OUTPUT_LOG = AXE_STATE_DIR / "logs" / "output.log"


def read_output_log_tail(lines: int = 1000) -> str:
    """Read the last N lines of the axe output log.

    Args:
        lines: Number of lines to read from the end (default: 1000).

    Returns:
        String containing the last N lines with ANSI codes preserved.
    """
    if not AXE_OUTPUT_LOG.exists():
        return ""

    try:
        with open(AXE_OUTPUT_LOG) as f:
            # Use deque with maxlen for memory-efficient tailing
            last_lines = deque(f, maxlen=lines)
        return "".join(last_lines)
    except OSError:
        return ""


def clear_output_log() -> None:
    """Clear the axe output log file."""
    if AXE_OUTPUT_LOG.exists():
        try:
            AXE_OUTPUT_LOG.write_text("")
        except OSError:
            pass


# --- Utility ---


def get_timestamp() -> str:
    """Get current timestamp in ISO format with timezone.

    Returns:
        ISO formatted timestamp string.
    """
    return datetime.now(EASTERN_TZ).isoformat()


# ---------------------------------------------------------------------------
# Per-lumberjack state management
# ---------------------------------------------------------------------------


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


def _lumberjack_dir(name: str) -> Path:
    """Return the state directory for a given lumberjack.

    Args:
        name: Lumberjack name (e.g. "hooks", "checks").

    Returns:
        Path to ``~/.sase/axe/lumberjacks/{name}/``.
    """
    return LUMBERJACK_STATE_DIR / name


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
    lj_dir = _lumberjack_dir(name)
    (lj_dir / "logs").mkdir(parents=True, exist_ok=True)
    return lj_dir


def write_lumberjack_pid(name: str) -> None:
    """Write PID file for a lumberjack process.

    Args:
        name: Lumberjack name.
    """
    lj_dir = ensure_lumberjack_dirs(name)
    (lj_dir / "pid").write_text(str(os.getpid()))


def read_lumberjack_pid(name: str) -> int | None:
    """Read PID for a lumberjack process.

    Args:
        name: Lumberjack name.

    Returns:
        PID as integer, or None if not found.
    """
    pid_file = _lumberjack_dir(name) / "pid"
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
    pid_file = _lumberjack_dir(name) / "pid"
    try:
        pid_file.unlink()
    except OSError:
        pass


def write_lumberjack_status(status: LumberjackStatus) -> None:
    """Write lumberjack status to disk.

    Args:
        status: Current lumberjack status.
    """
    lj_dir = ensure_lumberjack_dirs(status.name)
    _atomic_write_json(lj_dir / "status.json", asdict(status))


def read_lumberjack_status(name: str) -> LumberjackStatus | None:
    """Read lumberjack status from disk.

    Args:
        name: Lumberjack name.

    Returns:
        LumberjackStatus, or None if not available.
    """
    status_file = _lumberjack_dir(name) / "status.json"
    data = _read_json(status_file)
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
    lj_dir = ensure_lumberjack_dirs(name)
    _atomic_write_json(lj_dir / "metrics.json", asdict(metrics))


def read_lumberjack_metrics(name: str) -> LumberjackMetrics | None:
    """Read lumberjack metrics from disk.

    Args:
        name: Lumberjack name.

    Returns:
        LumberjackMetrics, or None if not available.
    """
    metrics_file = _lumberjack_dir(name) / "metrics.json"
    data = _read_json(metrics_file)
    if data is None:
        return None
    try:
        return LumberjackMetrics(**data)
    except TypeError:
        return None


def lumberjack_log_path(name: str) -> Path:
    """Return the output log path for a lumberjack.

    Args:
        name: Lumberjack name.

    Returns:
        Path to ``~/.sase/axe/lumberjacks/{name}/logs/output.log``.
    """
    return _lumberjack_dir(name) / "logs" / "output.log"


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
    try:
        with open(log_file) as f:
            last_lines = deque(f, maxlen=lines)
        return "".join(last_lines)
    except OSError:
        return ""


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
    if not LUMBERJACK_STATE_DIR.exists():
        return []
    return sorted(d.name for d in LUMBERJACK_STATE_DIR.iterdir() if d.is_dir())


def ensure_shared_dir() -> Path:
    """Create and return the shared state directory.

    Returns:
        Path to ``~/.sase/axe/shared/``.
    """
    SHARED_STATE_DIR.mkdir(parents=True, exist_ok=True)
    return SHARED_STATE_DIR
