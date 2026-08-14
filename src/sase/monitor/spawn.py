"""Launching, acknowledging, and killing the detached monitor supervisor.

Split out of :mod:`sase.monitor.start`: everything here is about the
supervisor *process* -- the double-fork bootstrap handshake that yields a
reparented grandchild, the startup acknowledgement that proves it survived
its own startup, and the teardown a failed start needs. The start flow that
drives it lives in :mod:`sase.monitor.start`.
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from sase.agent.env_hygiene import scrub_agent_identity_env

from .identity import supervisor_is_alive
from .transaction import MONITOR_START_ACK_TIMEOUT_SECONDS, monitor_started_path

SUPERVISOR_LOG_NAME = "supervisor.log"
_SUPERVISOR_BOOTSTRAP_PID_TIMEOUT_SECONDS = 5.0
_SUPERVISOR_STOP_POLL_SECONDS = 0.05
_SUPERVISOR_ACK_POLL_SECONDS = 0.05


class SupervisorSpawnError(RuntimeError):
    """Raised when the bootstrap process cannot report the real supervisor."""


@dataclass(frozen=True)
class DetachedSupervisor:
    """The real supervisor is a reparented grandchild, not the Popen child."""

    pid: int
    identity: str | None = None


def spawn_detached_supervisor(artifacts_dir: str) -> DetachedSupervisor:
    """Start the bootstrap and return the reparented supervisor grandchild."""
    env = _supervisor_env()
    supervisor_log = _open_supervisor_log(artifacts_dir)
    stdout: int | BinaryIO = supervisor_log or subprocess.DEVNULL
    try:
        return _spawn_bootstrap(artifacts_dir, env=env, stdout=stdout)
    finally:
        if supervisor_log is not None:
            supervisor_log.close()


def wait_for_start_acknowledgement(
    artifacts_dir: str,
    supervisor: DetachedSupervisor,
) -> str | None:
    """Block until the supervisor proves it is alive, or return an error.

    Polls the supervisor's own liveness alongside the marker so a supervisor
    that died outright fails fast instead of waiting out the full budget.
    """
    marker_path = monitor_started_path(artifacts_dir)
    deadline = time.monotonic() + MONITOR_START_ACK_TIMEOUT_SECONDS
    while True:
        if marker_path.exists():
            return None
        if not supervisor_is_alive(supervisor.pid, supervisor.identity):
            return (
                "monitor supervisor died without acknowledging startup; "
                "no process group was recorded"
            )
        if time.monotonic() >= deadline:
            return (
                "monitor supervisor did not acknowledge startup within "
                f"{MONITOR_START_ACK_TIMEOUT_SECONDS:g}s"
            )
        time.sleep(_SUPERVISOR_ACK_POLL_SECONDS)


def terminate_supervisor(supervisor: DetachedSupervisor) -> None:
    """Stop a supervisor a failed start must not leave running."""
    try:
        os.kill(supervisor.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    if not _wait_for_supervisor_exit(supervisor, timeout=5.0):
        try:
            os.kill(supervisor.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        _wait_for_supervisor_exit(supervisor, timeout=1.0)


def _supervisor_env() -> dict[str, str]:
    env = os.environ.copy()
    scrub_agent_identity_env(env)
    # SASE_ARTIFACTS_DIR does not carry the SASE_AGENT_ prefix the scrubber
    # matches on, but it still names the (possibly dead) starter's own
    # artifacts and must not leak into the detached supervisor.
    env.pop("SASE_ARTIFACTS_DIR", None)
    return env


def _spawn_bootstrap(
    artifacts_dir: str,
    *,
    env: dict[str, str],
    stdout: int | BinaryIO,
) -> DetachedSupervisor:
    read_fd, write_fd = os.pipe()
    launcher: subprocess.Popen[bytes] | None = None
    try:
        launcher = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).with_name("supervisor_bootstrap.py")),
                "--artifacts-dir",
                artifacts_dir,
                "--pid-fd",
                str(write_fd),
            ],
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            pass_fds=(write_fd,),
            env=env,
        )
        os.close(write_fd)
        write_fd = -1
        pid = _read_supervisor_pid(read_fd, launcher)
        _wait_for_bootstrap_exit(launcher)
        return DetachedSupervisor(pid)
    finally:
        for fd in (read_fd, write_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if launcher is not None and launcher.poll() is None:
            _terminate_bootstrap(launcher)


def _read_supervisor_pid(
    read_fd: int,
    launcher: subprocess.Popen[bytes],
) -> int:
    deadline = time.monotonic() + _SUPERVISOR_BOOTSTRAP_PID_TIMEOUT_SECONDS
    chunks: list[bytes] = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_bootstrap(launcher)
            raise SupervisorSpawnError("timed out waiting for supervisor pid")
        ready, _, _ = select.select([read_fd], [], [], remaining)
        if not ready:
            continue
        chunk = os.read(read_fd, 4096)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\n" in chunk:
            break

    raw = b"".join(chunks).splitlines()[0] if chunks else b""
    if not raw:
        detail = _bootstrap_exit_detail(launcher)
        raise SupervisorSpawnError(f"bootstrap exited without reporting a pid{detail}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupervisorSpawnError("bootstrap reported an invalid pid payload") from exc
    if not isinstance(payload, dict):
        raise SupervisorSpawnError("bootstrap reported a non-object pid payload")
    error = payload.get("error")
    if isinstance(error, str) and error:
        raise SupervisorSpawnError(error)
    try:
        pid = int(payload["pid"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SupervisorSpawnError("bootstrap did not report a valid pid") from exc
    if pid <= 0:
        raise SupervisorSpawnError("bootstrap reported a non-positive pid")
    return pid


def _wait_for_bootstrap_exit(launcher: subprocess.Popen[bytes]) -> None:
    try:
        returncode = launcher.wait(timeout=_SUPERVISOR_BOOTSTRAP_PID_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        _terminate_bootstrap(launcher)
        raise SupervisorSpawnError("bootstrap did not exit after forking") from exc
    if returncode != 0:
        raise SupervisorSpawnError(f"bootstrap exited with status {returncode}")


def _bootstrap_exit_detail(launcher: subprocess.Popen[bytes]) -> str:
    returncode = launcher.poll()
    if returncode is None:
        return ""
    return f" before exiting with status {returncode}"


def _terminate_bootstrap(launcher: subprocess.Popen[bytes]) -> None:
    try:
        launcher.terminate()
    except (ProcessLookupError, PermissionError):
        pass
    try:
        launcher.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        try:
            launcher.kill()
        except (ProcessLookupError, PermissionError):
            pass
        launcher.wait()


def _wait_for_supervisor_exit(
    supervisor: DetachedSupervisor,
    *,
    timeout: float,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not supervisor_is_alive(supervisor.pid, supervisor.identity):
            return True
        time.sleep(_SUPERVISOR_STOP_POLL_SECONDS)
    return not supervisor_is_alive(supervisor.pid, supervisor.identity)


def _open_supervisor_log(artifacts_dir: str) -> BinaryIO | None:
    """Open the detached supervisor's diagnostic stream when possible."""

    try:
        return (Path(artifacts_dir) / SUPERVISOR_LOG_NAME).open("ab")
    except OSError:
        return None


__all__ = [
    "SUPERVISOR_LOG_NAME",
    "DetachedSupervisor",
    "SupervisorSpawnError",
    "spawn_detached_supervisor",
    "terminate_supervisor",
    "wait_for_start_acknowledgement",
]
