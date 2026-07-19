"""Shutdown and process-sweeping helpers for the axe daemon."""

import os
import signal
import subprocess
import time

from . import _process_probe as process_probe
from .desired_state import write_desired_state
from .lock import clear_lock_holder_pid, is_lifecycle_lock_held
from .state import (
    list_lumberjack_names,
    read_lumberjack_pid,
    remove_lumberjack_pid,
)
from ._process_probe import cleanup_pid_files, probe_orchestrator
from ._process_types import AxeStopResult, SweepResult, TerminateResult


def stop_axe_daemon(
    timeout: float = 15.0,
    kill_timeout: float = 5.0,
    *,
    force: bool = False,
    desired_state_source: str = "stop",
    record_desired_state: bool = True,
) -> bool:
    """Stop the running axe orchestrator and wait for full shutdown.

    Sends SIGTERM for graceful shutdown (orchestrator forwards to children),
    then polls until the process exits. If the process doesn't exit within
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
        desired_state_source=desired_state_source,
        record_desired_state=record_desired_state,
    ).terminated_anything


def stop_axe_daemon_result(
    timeout: float = 15.0,
    kill_timeout: float = 5.0,
    *,
    force: bool = False,
    desired_state_source: str = "stop",
    record_desired_state: bool = True,
) -> AxeStopResult:
    """Stop axe and return a detailed lifecycle result."""
    if record_desired_state:
        write_desired_state("stopped", source=desired_state_source)

    probe = probe_orchestrator()
    pid = probe.running_pid or probe.lock_holder_pid
    if pid == os.getpid():
        pid = None
    orchestrator_result = TerminateResult()
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

    final_probe = probe_orchestrator(cleanup=False)
    should_clear_state = (
        force
        or orchestrator_result.stopped
        or (pid is not None and not process_probe.is_process_running(pid))
        or not final_probe.running
    )
    if should_clear_state:
        stopped_pid = pid if orchestrator_result.stopped else None
        cleanup_pid_files(stopped_pid=stopped_pid)
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

    return AxeStopResult(
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


def _send_signal(
    pid: int,
    sig: signal.Signals,
    *,
    prefer_group: bool = False,
    signaled_groups: set[int] | None = None,
) -> bool:
    """Send *sig* to a PID or, when safe, its process group."""
    if pid == os.getpid():
        return False

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
) -> TerminateResult:
    """Terminate one process, escalating to SIGKILL on timeout."""
    if not process_probe.is_process_running(pid):
        return TerminateResult(pid=pid, stopped=True)

    signaled = _send_signal(pid, signal.SIGTERM, prefer_group=term_group)
    if not signaled:
        still_running = process_probe.is_process_running(pid)
        return TerminateResult(
            pid=pid,
            stopped=not still_running,
            failed=still_running,
        )
    if _wait_for_exit(pid, timeout):
        return TerminateResult(pid=pid, signaled=True, stopped=True)

    killed = _send_signal(
        pid,
        signal.SIGKILL,
        prefer_group=kill_group_on_timeout,
    )
    if not killed and kill_group_on_timeout:
        killed = _send_signal(pid, signal.SIGKILL, prefer_group=False)
    stopped = _wait_for_exit(pid, kill_timeout)
    return TerminateResult(
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
        remaining = {
            pid
            for pid in remaining
            if process_probe.is_process_running(pid) and not _pid_is_zombie(pid)
        }
        if remaining:
            time.sleep(0.1)
    return {
        pid
        for pid in remaining
        if process_probe.is_process_running(pid) and not _pid_is_zombie(pid)
    }


def _sweep_lumberjack_orphans(
    *,
    timeout: float,
    kill_timeout: float,
    force: bool,
) -> SweepResult:
    """Terminate live lumberjacks tracked by their PID files."""
    seen: list[tuple[str, int]] = []
    for name in list_lumberjack_names():
        pid = read_lumberjack_pid(name)
        if pid is None:
            continue
        if not process_probe.is_process_running(pid):
            remove_lumberjack_pid(name)
            continue
        seen.append((name, pid))

    if not seen:
        return SweepResult()

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
        if not process_probe.is_process_running(pid):
            stopped_pids.add(pid)
            remove_lumberjack_pid(name)
        elif force:
            remove_lumberjack_pid(name)
            failed_pids.add(pid)

    return SweepResult(
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
        if pid == current_pid or not process_probe.is_process_running(pid):
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
        if not process_probe.is_process_running(pid) or _pid_is_zombie(pid):
            return True
        time.sleep(0.1)
    return not process_probe.is_process_running(pid) or _pid_is_zombie(pid)


def _pid_is_zombie(pid: int) -> bool:
    """Return True when ``ps`` reports *pid* as a zombie process."""
    try:
        completed = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if completed.returncode != 0:
        return False
    return completed.stdout.strip().startswith("Z")
