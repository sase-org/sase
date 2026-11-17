"""Monitored-command process control for the detached supervisor.

Owns the child process group from spawn through exit: launching the command,
enforcing the total/idle timeout budgets, and forwarding stop signals to the
whole process group rather than just the supervisor itself.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from typing import Any, cast

from sase.logs.pipe import BoundedLogPipe

from ._supervise_shared import TimeoutKind, format_duration
from .output import OutputCapture
from .transaction import (
    MONITOR_LAUNCH_BARRIER_TIMEOUT_SECONDS,
    monitor_go_path,
)

_POLL_SECONDS = 0.05
_KILL_GRACE_SECONDS = 5.0


class SupervisorTermination:
    """Forward stop/timeout signals to the monitored command's process group."""

    def __init__(self) -> None:
        self.requested = False
        self.requested_signum: int | None = None
        self.child: subprocess.Popen[bytes] | None = None
        self.kill_deadline: float | None = None

    def request(self, _signum: int, _frame: object) -> None:
        self.requested = True
        if self.requested_signum is None:
            self.requested_signum = _signum
        self._signal_child()

    def trigger_timeout(self) -> None:
        self._signal_child()

    def attach(self, child: subprocess.Popen[bytes]) -> None:
        self.child = child
        if self.requested:
            self._signal_child()

    def maybe_escalate(self) -> None:
        if (
            self.kill_deadline is not None
            and self.child is not None
            and self.child.poll() is None
            and time.monotonic() >= self.kill_deadline
        ):
            _signal_group(self.child.pid, signal.SIGKILL)
            self.kill_deadline = None

    def _signal_child(self) -> None:
        if self.child is not None and self.child.poll() is None:
            _signal_group(self.child.pid, signal.SIGTERM)
            self.kill_deadline = time.monotonic() + _KILL_GRACE_SECONDS

    def terminate_after_failure(self) -> None:
        """Best-effort TERM->KILL cleanup for an internally failing supervisor."""
        if self.child is None or self.child.poll() is not None:
            return
        _signal_group(self.child.pid, signal.SIGTERM)
        try:
            self.child.wait(timeout=_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _signal_group(self.child.pid, signal.SIGKILL)
            self.child.wait()

    def before_command_start_message(self) -> str:
        signal_name = _signal_name(self.requested_signum)
        return f"monitor stopped by {signal_name} before command start; command was not run"


class SupervisorOutputActivity:
    """Track output arrival from the drain thread for idle-timeout checks."""

    def __init__(self, capture: OutputCapture) -> None:
        self._capture = capture
        self._lock = threading.Lock()
        self._last_chunk_at = time.monotonic()

    def append_bytes(self, chunk: bytes) -> None:
        self._capture.append_bytes(chunk)
        with self._lock:
            self._last_chunk_at = time.monotonic()

    def idle_seconds(self) -> float:
        with self._lock:
            return time.monotonic() - self._last_chunk_at


def _signal_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except (ProcessLookupError, PermissionError):
        pass


def _signal_name(signum: int | None) -> str:
    if signum is None:
        return "a stop signal"
    try:
        return signal.Signals(signum).name
    except ValueError:
        return f"signal {signum}"


def popen_monitored_command(
    meta: dict[str, Any],
    *,
    command: str,
    cwd: str,
    output_pipe: BoundedLogPipe,
    command_env: dict[str, str],
) -> subprocess.Popen[bytes]:
    execution_argv = _execution_argv(meta)
    if execution_argv is not None:
        args: str | list[str] = execution_argv
        shell = False
    else:
        args = command
        shell = True
    return subprocess.Popen(
        args,
        shell=shell,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=cast(Any, output_pipe),
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
        text=False,
        env=command_env,
    )


def _execution_argv(meta: dict[str, Any]) -> list[str] | None:
    raw = meta.get("monitor_execution_argv")
    if not isinstance(raw, list) or not raw:
        return None
    argv = [str(part) for part in raw]
    if not all(argv):
        return None
    return argv


def wait_for_launch_barrier(
    artifacts_dir: str,
    termination: SupervisorTermination,
) -> str | None:
    """Wait until ``start_monitor`` releases the supervisor to exec."""
    marker_path = monitor_go_path(artifacts_dir)
    deadline = time.monotonic() + MONITOR_LAUNCH_BARRIER_TIMEOUT_SECONDS
    while True:
        if termination.requested:
            return termination.before_command_start_message()
        if marker_path.exists():
            return None
        if time.monotonic() >= deadline:
            timeout = format_duration(MONITOR_LAUNCH_BARRIER_TIMEOUT_SECONDS)
            return (
                "monitor start barrier was not released within "
                f"{timeout}; command was not run"
            )
        time.sleep(_POLL_SECONDS)


def wait_for_child(
    child: subprocess.Popen[bytes],
    termination: SupervisorTermination,
    timeout_seconds: float,
    idle_timeout_seconds: float,
    activity: SupervisorOutputActivity,
) -> TimeoutKind | None:
    """Wait for process exit; return which timeout budget fired, if any."""
    deadline = time.monotonic() + timeout_seconds if timeout_seconds > 0 else None
    timeout_kind: TimeoutKind | None = None
    while True:
        if child.poll() is not None:
            return timeout_kind
        now = time.monotonic()
        if deadline is not None and timeout_kind is None and now >= deadline:
            timeout_kind = "total"
            termination.trigger_timeout()
        if (
            idle_timeout_seconds > 0
            and timeout_kind is None
            and activity.idle_seconds() >= idle_timeout_seconds
        ):
            timeout_kind = "idle"
            termination.trigger_timeout()
        termination.maybe_escalate()
        time.sleep(_POLL_SECONDS)


__all__ = [
    "SupervisorOutputActivity",
    "SupervisorTermination",
    "popen_monitored_command",
    "wait_for_child",
    "wait_for_launch_barrier",
]
