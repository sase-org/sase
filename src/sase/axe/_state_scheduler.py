"""Legacy flat scheduler state (status, metrics, errors, cycle results).

Internal helper module — public API is re-exported through
``sase.axe.state``. Do not import from this module directly.

Paths and shared helpers are looked up through ``sase.axe.state`` at call
time so home-directory redirection applies to every reader.
"""

import sase.axe.state as _state  # noqa: I001
from sase.core.state_write_guard import best_effort_test_state_write_allowed
from dataclasses import asdict, dataclass, field
from typing import Literal


@dataclass
class AxeStatus:
    """Current status of the axe scheduler for TUI display."""

    pid: int
    started_at: str
    status: Literal["running", "stopped", "error"]
    full_check_interval: int
    hook_interval: int
    max_hook_runners: int
    max_agent_runners: int
    query: str
    zombie_timeout: int
    current_hook_runners: int
    current_agent_runners: int
    last_full_cycle: str | None
    last_hook_cycle: str | None
    next_full_cycle: str | None
    total_patches: int
    filtered_patches: int
    uptime_seconds: int


@dataclass
class CycleResult:
    """Result of a scheduler cycle for logging/debugging."""

    timestamp: str
    cycle_type: Literal["full", "hook", "comment"]
    duration_ms: int
    patches_processed: int
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


# --- PID File ---


def read_pid_file() -> int | None:
    """Read PID from file.

    Returns:
        PID as integer, or None if file doesn't exist or is invalid.
    """
    pid_file = _state.axe_state_dir() / "pid"
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def remove_pid_file() -> None:
    """Remove PID file on shutdown."""
    pid_file = _state.axe_state_dir() / "pid"
    if not best_effort_test_state_write_allowed(pid_file, category="axe-pid"):
        return
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
    status_file = _state.axe_state_dir() / "status.json"
    data = _state.read_json(status_file)
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
    result_file = _state.axe_state_dir() / filename
    _state.atomic_write_json(result_file, asdict(result))


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
    result_file = _state.axe_state_dir() / filename
    data = _state.read_json(result_file)
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
    metrics_file = _state.axe_state_dir() / "metrics.json"
    data = _state.read_json(metrics_file)
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
    errors_file = _state.axe_state_dir() / "recent_errors.json"
    errors: list[dict] = _state.read_json(errors_file) or []  # type: ignore[assignment]
    if not isinstance(errors, list):
        errors = []

    errors.append(error_info)
    # Keep only last 100 errors
    errors = errors[-100:]

    _state.atomic_write_json(errors_file, errors)


def read_errors() -> list[dict]:
    """Read recent errors from disk.

    Returns:
        List of error dictionaries, or empty list if none.
    """
    errors_file = _state.axe_state_dir() / "recent_errors.json"
    errors = _state.read_json(errors_file)
    if errors is None or not isinstance(errors, list):
        return []
    return errors


def write_last_error_digest_ts(ts: str) -> None:
    """Write the timestamp of the newest error in the last digest notification.

    Args:
        ts: ISO formatted timestamp string.
    """
    ts_file = _state.axe_state_dir() / "last_error_digest_ts"
    if not best_effort_test_state_write_allowed(ts_file, category="axe-error-state"):
        return
    ts_file.parent.mkdir(parents=True, exist_ok=True)
    ts_file.write_text(ts)


def read_last_error_digest_ts() -> str | None:
    """Read the high-water mark timestamp from the last error digest.

    Returns:
        ISO timestamp string, or None if file is missing or empty.
    """
    ts_file = _state.axe_state_dir() / "last_error_digest_ts"
    if not ts_file.exists():
        return None
    try:
        content = ts_file.read_text().strip()
        return content if content else None
    except OSError:
        return None


# --- Output Log ---


def read_output_log_tail(lines: int = 1000) -> str:
    """Read the last N lines of the axe output log.

    Args:
        lines: Number of lines to read from the end (default: 1000).

    Returns:
        String containing the last N lines with ANSI codes preserved.
    """
    output_log = _state.axe_output_log_path()
    if not output_log.exists():
        return ""
    return _state.read_tail_seek(output_log, lines)
