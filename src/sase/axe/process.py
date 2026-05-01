"""Process control for sase axe daemon.

This module provides functions for sase ace to start, stop, and monitor
the axe daemon process.  In the new architecture the daemon is an
Orchestrator that manages individual Lumberjack sub-processes.
"""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from sase.ace.changespec import count_agent_runners_global, count_hook_runners_global
from sase.ace.hooks.processes import is_process_running

from .config import AxeConfig, load_axe_config
from .lock import AXE_LOCK_FD_ENV, AxeLifecycleLock
from .orchestrator import ORCHESTRATOR_PID_FILE
from .state import (
    AXE_STATE_DIR,
    read_lumberjack_status,
    read_status,
)


def is_axe_running() -> bool:
    """Check if the axe orchestrator is currently running.

    Returns:
        True if axe is running, False otherwise.
    """
    pid = get_axe_pid()
    return pid is not None


def start_axe_daemon(config: AxeConfig | None = None) -> int | None:
    """Start axe as a background daemon process.

    Launches ``sase axe`` (orchestrator mode) as a detached subprocess.

    Args:
        config: Optional AxeConfig; loaded from disk if not provided.

    Returns:
        PID of the running process, or None if startup failed.
    """
    existing_pid = get_axe_pid()
    if existing_pid is not None:
        return existing_pid

    lifecycle_lock = _acquire_lifecycle_lock_for_start()
    if lifecycle_lock is None:
        return get_axe_pid()

    handed_off = False
    process: subprocess.Popen[bytes] | None = None
    try:
        existing_pid = get_axe_pid()
        if existing_pid is not None:
            return existing_pid

        if config is None:
            config = load_axe_config()

        cmd = _build_axe_start_command(config)
        if cmd is None:
            return None

        log_dir = AXE_STATE_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "axe.log"

        env = os.environ.copy()
        env[AXE_LOCK_FD_ENV] = str(lifecycle_lock.fd)
        with open(log_file, "a") as log:
            process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                pass_fds=(lifecycle_lock.fd,),
                env=env,
            )
        handed_off = True
        lifecycle_lock.close_after_handoff()
    finally:
        if not handed_off:
            lifecycle_lock.release()

    if process is None:
        return None
    return _wait_for_daemon_start(process)


def _acquire_lifecycle_lock_for_start(
    timeout: float = 15.0,
) -> AxeLifecycleLock | None:
    """Acquire the lifecycle lock, waiting through startup/shutdown races."""
    deadline = time.monotonic() + timeout
    while True:
        existing_pid = get_axe_pid()
        if existing_pid is not None:
            return None

        lifecycle_lock = AxeLifecycleLock.acquire(blocking=False)
        if lifecycle_lock is not None:
            return lifecycle_lock

        if time.monotonic() >= deadline:
            return None
        time.sleep(0.05)


def _build_axe_start_command(config: AxeConfig) -> list[str] | None:
    """Build the detached orchestrator command."""
    # Find sase executable — prefer the one next to the running interpreter
    bin_dir = Path(sys.executable).parent
    sase_in_bin = bin_dir / "sase"
    sase_cmd = str(sase_in_bin) if sase_in_bin.exists() else shutil.which("sase")
    if sase_cmd is None:
        return None

    cmd = [
        sase_cmd,
        "axe",
        "start",
        "--max-hook-runners",
        str(config.max_hook_runners),
        "--max-agent-runners",
        str(config.max_agent_runners),
        "--zombie-timeout",
        str(config.zombie_timeout_seconds),
    ]
    if config.query:
        cmd.extend(["-q", config.query])
    return cmd


def _wait_for_daemon_start(
    process: subprocess.Popen[bytes],
    timeout: float = 3.0,
) -> int | None:
    """Wait for the spawned orchestrator to publish a live PID."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = get_axe_pid()
        if pid is not None:
            return pid
        if process.poll() is not None:
            return get_axe_pid()
        time.sleep(0.05)

    if process.poll() is None and is_process_running(process.pid):
        return process.pid
    return get_axe_pid()


def stop_axe_daemon(
    timeout: float = 15.0,
    kill_timeout: float = 5.0,
) -> bool:
    """Stop the running axe orchestrator and wait for full shutdown.

    Sends SIGTERM for graceful shutdown (orchestrator forwards to children),
    then polls until the process exits.  If the process doesn't exit within
    *timeout* seconds, escalates to SIGKILL.

    Args:
        timeout: Seconds to wait after SIGTERM before sending SIGKILL.
        kill_timeout: Seconds to wait after SIGKILL before giving up.

    Returns:
        True if process was stopped, False if not running.
    """
    pid = get_axe_pid()
    if pid is None:
        return False

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        _cleanup_pid_file()
        return False

    _cleanup_pid_file()

    # Wait for the orchestrator (and its children) to exit.
    if _wait_for_exit(pid, timeout):
        return True

    # Escalate: SIGKILL the orchestrator process group.
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        _cleanup_pid_file()
        return True

    _wait_for_exit(pid, kill_timeout)
    _cleanup_pid_file()
    return True


def restart_axe_daemon(config: AxeConfig | None = None) -> int | None:
    """Restart the axe orchestrator and return the new/live PID."""
    stop_axe_daemon()
    return start_axe_daemon(config)


def _wait_for_exit(pid: int, timeout: float) -> bool:
    """Poll until *pid* is no longer running or *timeout* elapses.

    Returns True if the process exited, False on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_process_running(pid):
            return True
        time.sleep(0.1)
    return False


def get_axe_status() -> dict | None:
    """Get current axe daemon status for TUI display.

    Aggregates the orchestrator status with per-lumberjack statuses.

    Returns:
        Status dict, or None if not running.
    """
    pid = get_axe_pid()
    if pid is None:
        return None

    status = read_status()
    if status is not None:
        result: dict = {
            "pid": status.pid,
            "started_at": status.started_at,
            "status": status.status,
            "full_check_interval": status.full_check_interval,
            "hook_interval": status.hook_interval,
            "max_hook_runners": status.max_hook_runners,
            "max_agent_runners": status.max_agent_runners,
            "zombie_timeout": status.zombie_timeout,
            "query": status.query,
            "current_hook_runners": status.current_hook_runners,
            "current_agent_runners": status.current_agent_runners,
            "last_full_cycle": status.last_full_cycle,
            "last_hook_cycle": status.last_hook_cycle,
            "next_full_cycle": status.next_full_cycle,
            "total_changespecs": status.total_changespecs,
            "filtered_changespecs": status.filtered_changespecs,
            "uptime_seconds": status.uptime_seconds,
        }
    else:
        # No legacy status.json — construct from config + live data
        config = load_axe_config()
        result = {
            "pid": pid,
            "started_at": "",
            "status": "running",
            "full_check_interval": 0,
            "hook_interval": 0,
            "max_hook_runners": config.max_hook_runners,
            "max_agent_runners": config.max_agent_runners,
            "zombie_timeout": config.zombie_timeout_seconds,
            "query": config.query,
            "current_hook_runners": 0,
            "current_agent_runners": 0,
            "last_full_cycle": None,
            "last_hook_cycle": None,
            "next_full_cycle": None,
            "total_changespecs": 0,
            "filtered_changespecs": 0,
            "uptime_seconds": 0,
        }

    # Append per-lumberjack statuses
    lumberjacks_status: dict[str, dict] = {}
    lumberjack_start_times: list[str] = []
    for name in get_lumberjack_names():
        lumberjack_status = read_lumberjack_status(name)
        if lumberjack_status is not None:
            lumberjacks_status[name] = {
                "pid": lumberjack_status.pid,
                "status": lumberjack_status.status,
                "interval": lumberjack_status.interval,
                "chops": lumberjack_status.chops,
                "cycles_run": lumberjack_status.cycles_run,
                "errors_encountered": lumberjack_status.errors_encountered,
                "uptime_seconds": lumberjack_status.uptime_seconds,
            }
            lumberjack_start_times.append(lumberjack_status.started_at)
    if lumberjacks_status:
        result["lumberjacks"] = lumberjacks_status

    # Derive started_at and current runner counts from live data — the
    # legacy status.json is not written by the new orchestrator
    # architecture so its fields can be stale from a previous run.
    if lumberjack_start_times:
        result["started_at"] = min(lumberjack_start_times)
    result["current_hook_runners"] = count_hook_runners_global()
    result["current_agent_runners"] = count_agent_runners_global()

    return result


def get_axe_pid() -> int | None:
    """Get the PID of the running axe orchestrator.

    Checks the orchestrator PID file first, then falls back to the
    legacy global PID file for backward compatibility.

    Returns:
        PID if running, None otherwise.
    """
    # Check orchestrator PID file
    if ORCHESTRATOR_PID_FILE.exists():
        try:
            pid = int(ORCHESTRATOR_PID_FILE.read_text().strip())
        except (ValueError, OSError):
            pid = None
        if pid is not None:
            if is_process_running(pid):
                return pid
            _cleanup_pid_file()

    # Fall back to legacy PID file
    from .state import read_pid_file, remove_pid_file

    legacy_pid = read_pid_file()
    if legacy_pid is not None:
        if is_process_running(legacy_pid):
            return legacy_pid
        remove_pid_file()

    return None


def get_lumberjack_names() -> list[str]:
    """Return configured lumberjack names from the axe config.

    Returns:
        Sorted list of lumberjack names.
    """
    config = load_axe_config()
    return sorted(config.lumberjacks.keys())


def _cleanup_pid_file() -> None:
    """Remove all PID files (orchestrator + legacy)."""
    from .state import remove_pid_file

    try:
        ORCHESTRATOR_PID_FILE.unlink()
    except OSError:
        pass
    remove_pid_file()
