"""Process control for sase axe daemon.

This module provides functions for sase ace to start, stop, and monitor
the axe daemon process.  In the new architecture the daemon is an
Orchestrator that manages individual Lumberjack sub-processes.
"""

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.ace.changespec import count_agent_runners_global, count_hook_runners_global
from sase.ace.hooks.processes import is_process_running

from .config import AxeConfig, load_axe_config
from .lock import (
    AXE_LOCK_FD_ENV,
    AxeLifecycleLock,
    clear_lock_holder_pid,
    is_lifecycle_lock_held,
    read_lock_holder_pid,
)
from .orchestrator import ORCHESTRATOR_PID_FILE
from .state import (
    AXE_STATE_DIR,
    list_lumberjack_names,
    read_lumberjack_pid,
    read_lumberjack_status,
    read_status,
    remove_lumberjack_pid,
)


StartStatus = Literal["started", "already_running", "failed", "blocked"]


@dataclass(frozen=True)
class _AxeStartResult:
    """Result of an axe daemon start request."""

    status: StartStatus
    pid: int | None = None
    message: str = ""

    @property
    def succeeded(self) -> bool:
        return self.pid is not None


@dataclass(frozen=True)
class _AxeOrchestratorProbe:
    """Authoritative view of axe orchestrator liveness."""

    lock_held: bool
    lock_holder_pid: int | None
    orchestrator_pid_file_pid: int | None
    legacy_pid: int | None
    running_pid: int | None

    @property
    def running(self) -> bool:
        return self.lock_held or self.running_pid is not None


@dataclass(frozen=True)
class _AxeStopResult:
    """Result of an axe daemon stop request."""

    orchestrator_pid: int | None = None
    orchestrator_signaled: bool = False
    orchestrator_stopped: bool = False
    lumberjack_pids: tuple[int, ...] = ()
    lumberjacks_stopped: int = 0
    force_killed_processes: int = 0
    failed_pids: tuple[int, ...] = ()
    lock_was_held: bool = False
    lock_still_held: bool = False
    force: bool = False
    error: str | None = None

    @property
    def terminated_anything(self) -> bool:
        return (
            self.orchestrator_signaled
            or self.lumberjacks_stopped > 0
            or self.force_killed_processes > 0
        )

    @property
    def succeeded(self) -> bool:
        return self.terminated_anything and not self.failed_pids

    def summary(self) -> str:
        """Return a concise user-facing summary."""
        if self.error and not self.terminated_anything:
            return self.error
        parts: list[str] = []
        if self.orchestrator_signaled:
            if self.orchestrator_stopped:
                parts.append("orchestrator")
            else:
                parts.append("orchestrator signaled")
        if self.lumberjacks_stopped:
            parts.append(f"{self.lumberjacks_stopped} lumberjack(s)")
        if self.force_killed_processes:
            parts.append(f"{self.force_killed_processes} matched axe process(es)")
        if parts:
            return "Stopped " + " + ".join(parts)
        if self.lock_was_held and self.lock_still_held:
            return (
                "Axe lifecycle lock is still held, but no live PID could be "
                "resolved; retry with `sase axe stop --force`."
            )
        return "Axe orchestrator is not running."


@dataclass(frozen=True)
class _TerminateResult:
    pid: int | None = None
    signaled: bool = False
    stopped: bool = False
    failed: bool = False


@dataclass(frozen=True)
class _SweepResult:
    seen: tuple[tuple[str, int], ...] = ()
    stopped_pids: tuple[int, ...] = ()
    failed_pids: tuple[int, ...] = ()


def is_axe_running() -> bool:
    """Check if the axe orchestrator is currently running.

    Returns:
        True if axe is running, False otherwise.
    """
    return _probe_orchestrator().running


def start_axe_daemon(config: AxeConfig | None = None) -> int | None:
    """Start axe as a background daemon process.

    Launches ``sase axe`` (orchestrator mode) as a detached subprocess.

    Args:
        config: Optional AxeConfig; loaded from disk if not provided.

    Returns:
        PID of the running process, or None if startup failed.
    """
    return start_axe_daemon_result(config).pid


def start_axe_daemon_result(config: AxeConfig | None = None) -> _AxeStartResult:
    """Start axe as a background daemon process and return a detailed result."""
    existing_pid = get_axe_pid()
    if existing_pid is not None:
        return _AxeStartResult(
            status="already_running",
            pid=existing_pid,
            message=f"Axe is already running (pid {existing_pid}).",
        )

    lifecycle_lock = _acquire_lifecycle_lock_for_start()
    if lifecycle_lock is None:
        existing_pid = get_axe_pid()
        if existing_pid is not None:
            return _AxeStartResult(
                status="already_running",
                pid=existing_pid,
                message=f"Axe is already running (pid {existing_pid}).",
            )
        probe = _probe_orchestrator()
        if probe.lock_held:
            lock_holder = (
                f" by pid {probe.lock_holder_pid}"
                if probe.lock_holder_pid is not None
                else ""
            )
            return _AxeStartResult(
                status="blocked",
                message=(
                    f"Axe lifecycle lock is held{lock_holder}, but no live "
                    "orchestrator PID is published. Run `sase axe stop`; if "
                    "the lock remains stuck, run `sase axe stop --force`."
                ),
            )
        return _AxeStartResult(
            status="failed",
            message="Timed out acquiring the axe lifecycle lock.",
        )

    handed_off = False
    process: subprocess.Popen[bytes] | None = None
    try:
        existing_pid = _get_pid_from_pid_files()
        if existing_pid is not None:
            return _AxeStartResult(
                status="already_running",
                pid=existing_pid,
                message=f"Axe is already running (pid {existing_pid}).",
            )

        if config is None:
            config = load_axe_config()

        cmd = _build_axe_start_command(config)
        if cmd is None:
            return _AxeStartResult(
                status="failed",
                message="Could not find a `sase` executable to start axe.",
            )

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
                cwd=os.path.expanduser("~"),
            )
        handed_off = True
        lifecycle_lock.close_after_handoff()
    finally:
        if not handed_off:
            lifecycle_lock.release()

    if process is None:
        return _AxeStartResult(status="failed", message="Failed to spawn axe.")
    pid = _wait_for_daemon_start(process)
    if pid is not None:
        return _AxeStartResult(
            status="started",
            pid=pid,
            message=f"Axe started (pid {pid}).",
        )

    exit_code = process.poll()
    if exit_code is not None:
        return _AxeStartResult(
            status="failed",
            message=f"Axe start process exited before publishing a PID (code {exit_code}).",
        )
    probe = _probe_orchestrator()
    if probe.lock_held:
        lock_holder = (
            f" by pid {probe.lock_holder_pid}"
            if probe.lock_holder_pid is not None
            else ""
        )
        return _AxeStartResult(
            status="blocked",
            message=(
                f"Axe lifecycle lock is held{lock_holder}, but no live "
                "orchestrator PID is published. Run `sase axe stop`; if the "
                "lock remains stuck, run `sase axe stop --force`."
            ),
        )
    return _AxeStartResult(
        status="failed",
        message="Timed out waiting for axe to publish its daemon PID.",
    )


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


_EPHEMERAL_WORKSPACE_RE = re.compile(r"^sase_\d+$")


def _path_is_ephemeral_workspace(path: Path) -> bool:
    """Return True when *path* is inside a numbered SASE workspace clone."""
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    return any(_EPHEMERAL_WORKSPACE_RE.fullmatch(part) for part in resolved.parts)


def _running_from_ephemeral_workspace() -> bool:
    """Return True when this process appears to be inside an agent workspace."""
    paths: list[Path] = [Path(sys.executable)]
    try:
        paths.append(Path.cwd())
    except OSError:
        pass
    if any(_path_is_ephemeral_workspace(path) for path in paths):
        return True
    return any(
        os.environ.get(name)
        for name in (
            "SASE_AGENT_NAME",
            "SASE_AGENT_PROJECT_FILE",
            "SASE_AGENT_TIMESTAMP",
        )
    )


def _resolve_primary_workspace_sase() -> str | None:
    """Resolve a non-ephemeral primary workspace ``sase`` executable."""
    try:
        from sase.bead.workspace import resolve_primary_workspace

        primary = resolve_primary_workspace()
    except Exception:
        return None
    if primary is None or _path_is_ephemeral_workspace(primary):
        return None
    candidate = primary / ".venv" / "bin" / "sase"
    if candidate.exists():
        return str(candidate)
    return None


def _resolve_sase_executable(*, prefer_canonical: bool) -> str | None:
    """Find the best ``sase`` executable for launching long-lived daemons."""
    current_bin = Path(sys.executable).parent / "sase"
    current = str(current_bin) if current_bin.exists() else None
    path_sase = shutil.which("sase")

    candidates: list[str | None]
    if prefer_canonical:
        candidates = [
            str(Path.home() / ".local" / "bin" / "sase"),
            path_sase,
            _resolve_primary_workspace_sase(),
            current,
        ]
    else:
        candidates = [
            current,
            path_sase,
            str(Path.home() / ".local" / "bin" / "sase"),
        ]

    for candidate in candidates:
        if not candidate:
            continue
        candidate_path = Path(candidate)
        if candidate != path_sase and not candidate_path.exists():
            continue
        if prefer_canonical and _path_is_ephemeral_workspace(candidate_path):
            continue
        return str(candidate_path)
    return None


def should_reexec_axe_start_from_canonical() -> bool:
    """Return True when ``sase axe start`` should re-exec from a stable install."""
    if os.environ.get("SASE_AXE_CANONICALIZED"):
        return False
    return _running_from_ephemeral_workspace()


def canonical_axe_start_command() -> str | None:
    """Return a stable ``sase`` executable for axe daemon startup."""
    return _resolve_sase_executable(prefer_canonical=True)


def _build_axe_start_command(config: AxeConfig) -> list[str] | None:
    """Build the detached orchestrator command."""
    sase_cmd = _resolve_sase_executable(
        prefer_canonical=_running_from_ephemeral_workspace()
    )
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
    timeout: float = 15.0,
) -> int | None:
    """Wait for the spawned orchestrator to publish a live PID file."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = get_axe_pid()
        if pid is not None:
            return pid
        if process.poll() is not None:
            return None
        time.sleep(0.05)

    return get_axe_pid()


def stop_axe_daemon(
    timeout: float = 15.0,
    kill_timeout: float = 5.0,
    *,
    force: bool = False,
) -> bool:
    """Stop the running axe orchestrator and wait for full shutdown.

    Sends SIGTERM for graceful shutdown (orchestrator forwards to children),
    then polls until the process exits.  If the process doesn't exit within
    *timeout* seconds, escalates to SIGKILL.

    Args:
        timeout: Seconds to wait after SIGTERM before sending SIGKILL.
        kill_timeout: Seconds to wait after SIGKILL before giving up.
        force: Also kill matched axe worker processes and reset PID state.

    Returns:
        True if process was stopped, False if not running.
    """
    return stop_axe_daemon_result(
        timeout=timeout,
        kill_timeout=kill_timeout,
        force=force,
    ).terminated_anything


def stop_axe_daemon_result(
    timeout: float = 15.0,
    kill_timeout: float = 5.0,
    *,
    force: bool = False,
) -> _AxeStopResult:
    """Stop axe and return a detailed lifecycle result."""
    probe = _probe_orchestrator()
    pid = probe.running_pid or probe.lock_holder_pid
    orchestrator_result = _TerminateResult()
    if pid is not None:
        orchestrator_result = _terminate_process(
            pid,
            timeout=timeout,
            kill_timeout=kill_timeout,
            kill_group_on_timeout=True,
        )

    sweep = _sweep_lumberjack_orphans(
        timeout=min(timeout, 5.0),
        kill_timeout=min(kill_timeout, 2.0),
        force=force,
    )

    force_killed = 0
    if force:
        force_killed = _force_kill_matching_axe_processes(
            timeout=min(timeout, 3.0),
            kill_timeout=min(kill_timeout, 2.0),
        )

    final_probe = _probe_orchestrator(cleanup=False)
    should_clear_state = (
        force
        or orchestrator_result.stopped
        or (pid is not None and not is_process_running(pid))
        or not final_probe.running
    )
    if should_clear_state:
        _cleanup_pid_file()
        if not final_probe.lock_held or force:
            clear_lock_holder_pid()

    lock_still_held = is_lifecycle_lock_held()
    failed_pids = tuple(
        pid
        for pid in ([orchestrator_result.pid] if orchestrator_result.failed else [])
        + list(sweep.failed_pids)
        if pid is not None
    )
    error: str | None = None
    if probe.lock_held and pid is None and not sweep.stopped_pids and not force_killed:
        error = (
            "Axe lifecycle lock is held, but no live orchestrator PID could be "
            "resolved. Run `sase axe stop --force` to sweep matched axe "
            "processes and reset PID state."
        )

    return _AxeStopResult(
        orchestrator_pid=pid,
        orchestrator_signaled=orchestrator_result.signaled,
        orchestrator_stopped=orchestrator_result.stopped,
        lumberjack_pids=tuple(pid for _name, pid in sweep.seen),
        lumberjacks_stopped=len(sweep.stopped_pids),
        force_killed_processes=force_killed,
        failed_pids=failed_pids,
        lock_was_held=probe.lock_held,
        lock_still_held=lock_still_held,
        force=force,
        error=error,
    )


def restart_axe_daemon(config: AxeConfig | None = None) -> int | None:
    """Restart the axe orchestrator and return the new/live PID."""
    stop_axe_daemon()
    return start_axe_daemon(config)


def restart_axe_daemon_result(config: AxeConfig | None = None) -> _AxeStartResult:
    """Restart axe and return detailed startup status."""
    stop_axe_daemon_result()
    return start_axe_daemon_result(config)


def _send_signal(
    pid: int,
    sig: signal.Signals,
    *,
    prefer_group: bool = False,
    signaled_groups: set[int] | None = None,
) -> bool:
    """Send *sig* to a PID or, when safe, its process group."""
    if prefer_group:
        try:
            pgid = os.getpgid(pid)
        except (ProcessLookupError, PermissionError, OSError):
            pgid = None
        if pgid is not None and pgid not in {os.getpgrp(), os.getpid()}:
            if signaled_groups is not None and pgid in signaled_groups:
                return True
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                return False
            except PermissionError:
                return False
            if signaled_groups is not None:
                signaled_groups.add(pgid)
            return True

    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    return True


def _terminate_process(
    pid: int,
    *,
    timeout: float,
    kill_timeout: float,
    kill_group_on_timeout: bool = False,
    term_group: bool = False,
) -> _TerminateResult:
    """Terminate one process, escalating to SIGKILL on timeout."""
    if not is_process_running(pid):
        return _TerminateResult(pid=pid, stopped=True)

    signaled = _send_signal(pid, signal.SIGTERM, prefer_group=term_group)
    if not signaled:
        still_running = is_process_running(pid)
        return _TerminateResult(
            pid=pid,
            stopped=not still_running,
            failed=still_running,
        )
    if _wait_for_exit(pid, timeout):
        return _TerminateResult(pid=pid, signaled=True, stopped=True)

    killed = _send_signal(
        pid,
        signal.SIGKILL,
        prefer_group=kill_group_on_timeout,
    )
    if not killed and kill_group_on_timeout:
        killed = _send_signal(pid, signal.SIGKILL, prefer_group=False)
    stopped = _wait_for_exit(pid, kill_timeout)
    return _TerminateResult(
        pid=pid,
        signaled=True,
        stopped=stopped,
        failed=not stopped,
    )


def _wait_for_all_exited(pids: set[int], timeout: float) -> set[int]:
    """Wait until all PIDs exit and return those still running."""
    deadline = time.monotonic() + timeout
    remaining = set(pids)
    while remaining and time.monotonic() < deadline:
        remaining = {pid for pid in remaining if is_process_running(pid)}
        if remaining:
            time.sleep(0.1)
    return {pid for pid in remaining if is_process_running(pid)}


def _sweep_lumberjack_orphans(
    *,
    timeout: float,
    kill_timeout: float,
    force: bool,
) -> _SweepResult:
    """Terminate live lumberjacks tracked by their PID files."""
    seen: list[tuple[str, int]] = []
    for name in list_lumberjack_names():
        pid = read_lumberjack_pid(name)
        if pid is None:
            continue
        if not is_process_running(pid):
            remove_lumberjack_pid(name)
            continue
        seen.append((name, pid))

    if not seen:
        return _SweepResult()

    signaled_groups: set[int] = set()
    signaled_pids: set[int] = set()
    failed_pids: set[int] = set()
    for _name, pid in seen:
        if _send_signal(
            pid,
            signal.SIGTERM,
            prefer_group=True,
            signaled_groups=signaled_groups,
        ):
            signaled_pids.add(pid)
        else:
            failed_pids.add(pid)

    remaining = _wait_for_all_exited(signaled_pids, timeout)
    if remaining:
        signaled_groups.clear()
        for pid in remaining:
            if not _send_signal(
                pid,
                signal.SIGKILL,
                prefer_group=True,
                signaled_groups=signaled_groups,
            ):
                failed_pids.add(pid)
        remaining = _wait_for_all_exited(remaining, kill_timeout)

    stopped_pids: set[int] = set()
    for name, pid in seen:
        if not is_process_running(pid):
            stopped_pids.add(pid)
            remove_lumberjack_pid(name)
        elif force:
            remove_lumberjack_pid(name)
            failed_pids.add(pid)

    return _SweepResult(
        seen=tuple(seen),
        stopped_pids=tuple(sorted(stopped_pids)),
        failed_pids=tuple(sorted(failed_pids - stopped_pids)),
    )


def _force_kill_matching_axe_processes(
    *,
    timeout: float,
    kill_timeout: float,
) -> int:
    """Last-resort force sweep for axe processes without usable PID files."""
    matches = _matching_axe_process_pids()
    if not matches:
        return 0

    signaled_groups: set[int] = set()
    signaled_pids: set[int] = set()
    for pid in matches:
        if _send_signal(
            pid,
            signal.SIGTERM,
            prefer_group=True,
            signaled_groups=signaled_groups,
        ):
            signaled_pids.add(pid)

    remaining = _wait_for_all_exited(signaled_pids, timeout)
    if remaining:
        signaled_groups.clear()
        for pid in remaining:
            _send_signal(
                pid,
                signal.SIGKILL,
                prefer_group=True,
                signaled_groups=signaled_groups,
            )
        _wait_for_all_exited(remaining, kill_timeout)
    return len(matches)


def _matching_axe_process_pids() -> list[int]:
    """Return live axe process PIDs found by command-line matching."""
    try:
        completed = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return []
    if completed.returncode != 0:
        return []

    current_pid = os.getpid()
    pids: list[int] = []
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            pid_text, command = stripped.split(maxsplit=1)
            pid = int(pid_text)
        except ValueError:
            continue
        if pid == current_pid or not is_process_running(pid):
            continue
        if _is_matching_axe_process_command(command):
            pids.append(pid)
    return pids


def _is_matching_axe_process_command(command: str) -> bool:
    """Return True for long-lived axe orchestrator or lumberjack commands."""
    padded = f" {command} "
    if " axe stop" in padded:
        return False
    if "sase" not in command:
        return False
    return " axe lumberjack run " in padded or " axe start " in padded


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

    Reconciles the lifecycle lock with the orchestrator PID file and the
    legacy global PID file. The lock is authoritative for liveness; this
    function returns the best known live PID when one can be resolved.

    Returns:
        PID if running, None otherwise.
    """
    return _probe_orchestrator().running_pid


def _get_pid_from_pid_files() -> int | None:
    """Return a live PID from PID files without consulting the lifecycle lock."""
    orchestrator_pid = _read_pid_path(ORCHESTRATOR_PID_FILE)

    from .state import read_pid_file

    legacy_pid = read_pid_file()
    if orchestrator_pid is not None and is_process_running(orchestrator_pid):
        return orchestrator_pid
    if legacy_pid is not None and is_process_running(legacy_pid):
        return legacy_pid
    return None


def _probe_orchestrator(*, cleanup: bool = True) -> _AxeOrchestratorProbe:
    """Probe axe orchestrator liveness from lock and PID-file state."""
    lock_held = is_lifecycle_lock_held()
    lock_holder_pid = read_lock_holder_pid() if lock_held else None
    orchestrator_pid = _read_pid_path(ORCHESTRATOR_PID_FILE)

    from .state import read_pid_file, remove_pid_file

    legacy_pid = read_pid_file()

    lock_holder_running = lock_holder_pid is not None and is_process_running(
        lock_holder_pid
    )
    orchestrator_running = orchestrator_pid is not None and is_process_running(
        orchestrator_pid
    )
    legacy_running = legacy_pid is not None and is_process_running(legacy_pid)

    running_pid: int | None = None
    if lock_holder_running:
        running_pid = lock_holder_pid
    elif orchestrator_running:
        running_pid = orchestrator_pid
    elif legacy_running:
        running_pid = legacy_pid

    if cleanup:
        if orchestrator_pid is not None and not orchestrator_running:
            _remove_orchestrator_pid_file()
        if legacy_pid is not None and not legacy_running:
            remove_pid_file()
        if not lock_held and read_lock_holder_pid() is not None:
            clear_lock_holder_pid()

    return _AxeOrchestratorProbe(
        lock_held=lock_held,
        lock_holder_pid=lock_holder_pid,
        orchestrator_pid_file_pid=orchestrator_pid,
        legacy_pid=legacy_pid,
        running_pid=running_pid,
    )


def _read_pid_path(path: Path) -> int | None:
    """Read an integer PID from *path*."""
    if not path.exists():
        return None
    try:
        pid = int(path.read_text().strip())
    except (ValueError, OSError):
        return None
    return pid if pid > 0 else None


def _remove_orchestrator_pid_file() -> None:
    """Remove the orchestrator PID file."""
    try:
        ORCHESTRATOR_PID_FILE.unlink()
    except OSError:
        pass


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

    _remove_orchestrator_pid_file()
    remove_pid_file()
