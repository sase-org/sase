"""Launch, acknowledge, and tear down the detached proc supervisor."""

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

from sase.agent.env_hygiene import scrub_agent_identity_env, scrub_chop_context_env

from .identity import supervisor_is_alive
from .runtime import (
    proc_go_path,
    proc_runtime_dir,
    proc_started_path,
    start_ack_timeout_seconds,
    write_json_atomic,
)

_SUPERVISOR_LOG_NAME = "supervisor.log"
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


def spawn_detached_supervisor(proc_id: str) -> DetachedSupervisor:
    """Start the bootstrap and return the reparented supervisor grandchild."""
    env = _supervisor_env()
    supervisor_log = _open_supervisor_log(proc_id)
    stdout: int | BinaryIO = supervisor_log or subprocess.DEVNULL
    try:
        return _spawn_bootstrap(proc_id, env=env, stdout=stdout)
    finally:
        if supervisor_log is not None:
            supervisor_log.close()


def wait_for_start_acknowledgement(
    proc_id: str,
    supervisor: DetachedSupervisor,
) -> str | None:
    """Block until the supervisor proves it is alive, or return an error."""
    marker_path = proc_started_path(proc_id)
    deadline = time.monotonic() + start_ack_timeout_seconds()
    while True:
        if marker_path.exists():
            return None
        if not supervisor_is_alive(supervisor.pid, supervisor.identity):
            return (
                "proc supervisor died without acknowledging startup; "
                "command was not run"
            )
        if time.monotonic() >= deadline:
            timeout = start_ack_timeout_seconds()
            return f"proc supervisor did not acknowledge startup within {timeout:g}s"
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


def write_launch_barrier(proc_id: str, *, request_fingerprint: str) -> None:
    """Release the supervisor to exec the persisted argv."""
    write_json_atomic(
        proc_go_path(proc_id),
        {
            "proc_id": proc_id,
            "request_fingerprint": request_fingerprint,
            "timestamp": time.time(),
        },
    )


def _supervisor_env() -> dict[str, str]:
    env = os.environ.copy()
    scrub_agent_identity_env(env)
    scrub_chop_context_env(env)
    env.pop("SASE_ARTIFACTS_DIR", None)
    return env


def _spawn_bootstrap(
    proc_id: str,
    *,
    env: dict[str, str],
    stdout: int | BinaryIO,
) -> DetachedSupervisor:
    read_fd, write_fd = os.pipe()
    launcher: subprocess.Popen[bytes] | None = None
    try:
        try:
            launcher = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).with_name("supervisor_bootstrap.py")),
                    "--proc-id",
                    proc_id,
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
        except (OSError, ValueError) as exc:
            raise SupervisorSpawnError(str(exc)) from exc
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


def _open_supervisor_log(proc_id: str) -> BinaryIO | None:
    try:
        path = proc_runtime_dir(proc_id) / _SUPERVISOR_LOG_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open("ab")
    except OSError:
        return None


__all__ = [
    "DetachedSupervisor",
    "SupervisorSpawnError",
    "spawn_detached_supervisor",
    "terminate_supervisor",
    "wait_for_start_acknowledgement",
    "write_launch_barrier",
]
