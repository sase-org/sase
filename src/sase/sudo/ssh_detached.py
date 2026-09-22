"""Detached remote executors: liveness, ledger wait, and cleanup."""

from __future__ import annotations

import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Mapping
from typing import Any, BinaryIO, TextIO

from sase.notification_gates.models import GateError
from sase.sudo.ssh_defs import (
    LIVENESS_DEAD,
    LIVENESS_UNKNOWN,
    REMOTE_EXECUTOR_DEATH_GRACE_SECONDS,
    REMOTE_POLL_MAX_SECONDS,
    REMOTE_POLL_SECONDS,
    REMOTE_POLL_SSH_TIMEOUT_SECONDS,
    REMOTE_STOP_GRACE_SECONDS,
    SSH_TRANSPORT_FAILURE,
    CommandRunner,
    RemoteExecutorLiveness,
)
from sase.sudo.ssh_paths import paths_from_payload
from sase.sudo.ssh_transport import (
    backoff_sleep,
    copy_remote_output_log,
    fetch_json_file_optional,
    liveness_command,
    require_ssh_target,
    run_ssh,
    ssh_argv,
    write_remote_stop,
)


def wait_for_remote_sudo_ledger(
    host: str,
    paths_payload: Mapping[str, Any],
    *,
    handshake: Mapping[str, Any],
    command_runner: CommandRunner | None = None,
    timeout_seconds: float | None,
    dest: BinaryIO | TextIO | None = None,
) -> dict[str, Any]:
    """Poll a remote detached sudo executor until its ledger is readable."""
    runner = subprocess.run if command_runner is None else command_runner
    require_ssh_target(host)
    paths = paths_from_payload(paths_payload)
    timeout = 330.0 if timeout_seconds is None else max(0.0, float(timeout_seconds))
    deadline = time.monotonic() + timeout
    stop_deadline: float | None = None
    offset = 0
    delay = REMOTE_POLL_SECONDS
    output_dest = sys.stdout if dest is None else dest

    def _on_stop(_signum: int, _frame: object | None) -> None:
        nonlocal stop_deadline
        write_remote_stop(host, paths, command_runner=runner)
        if stop_deadline is None:
            stop_deadline = time.monotonic() + REMOTE_STOP_GRACE_SECONDS

    previous_term = signal.getsignal(signal.SIGTERM)
    previous_int = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)
    try:
        while True:
            offset = copy_remote_output_log(
                host,
                paths.log,
                offset=offset,
                dest=output_dest,
                command_runner=runner,
            )
            ledger = fetch_json_file_optional(
                host,
                paths.ledger,
                command_runner=runner,
                timeout=REMOTE_POLL_SSH_TIMEOUT_SECONDS,
            )
            if ledger is not None:
                copy_remote_output_log(
                    host,
                    paths.log,
                    offset=offset,
                    dest=output_dest,
                    command_runner=runner,
                )
                return ledger
            now = time.monotonic()
            if stop_deadline is not None and now >= stop_deadline:
                raise GateError(
                    "killed",
                    "sudo.finalize",
                    "sudo remote finalize was stopped; the gate remains pending",
                )
            if now >= deadline:
                raise GateError(
                    "timeout",
                    "sudo.finalize",
                    "remote sudo executor timed out; the gate remains pending",
                )
            liveness = _probe_remote_executor_liveness(
                host,
                handshake,
                command_runner=runner,
            )
            if liveness.classification == "dead":
                death_deadline = time.monotonic() + REMOTE_EXECUTOR_DEATH_GRACE_SECONDS
                while time.monotonic() < death_deadline:
                    offset = copy_remote_output_log(
                        host,
                        paths.log,
                        offset=offset,
                        dest=output_dest,
                        command_runner=runner,
                    )
                    ledger = fetch_json_file_optional(
                        host,
                        paths.ledger,
                        command_runner=runner,
                        timeout=REMOTE_POLL_SSH_TIMEOUT_SECONDS,
                    )
                    if ledger is not None:
                        copy_remote_output_log(
                            host,
                            paths.log,
                            offset=offset,
                            dest=output_dest,
                            command_runner=runner,
                        )
                        return ledger
                    time.sleep(REMOTE_POLL_SECONDS)
                raise GateError(
                    "executor_died",
                    "sudo.finalize",
                    (
                        "remote sudo executor exited without a ledger; "
                        "the gate remains pending"
                    ),
                )
            delay = backoff_sleep(delay, deadline)
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)


def cleanup_remote_sudo(
    host: str,
    paths_payload: Mapping[str, Any],
    *,
    command_runner: CommandRunner | None = None,
) -> bool:
    """Best-effort removal of remote handoff files.

    Return True when cleanup completed or the remote directory is already gone.
    Transient transport failures return False so the durable attempt is retained.
    """
    runner = subprocess.run if command_runner is None else command_runner
    try:
        require_ssh_target(host)
        paths = paths_from_payload(paths_payload)
    except GateError:
        return True
    delay = REMOTE_POLL_SECONDS
    for _attempt in range(3):
        completed = run_ssh(
            "remote_sudo_cleanup_failed",
            runner,
            ssh_argv(
                host,
                (
                    f"if [ ! -e {shlex.quote(paths.directory)} ]; then exit 0; fi; "
                    f"rm -rf {shlex.quote(paths.directory)}"
                ),
            ),
            kwargs={
                "check": False,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "timeout": REMOTE_POLL_SSH_TIMEOUT_SECONDS,
            },
            raise_timeout=False,
        )
        if completed is None:
            time.sleep(delay)
            delay = min(delay * 2, REMOTE_POLL_MAX_SECONDS)
            continue
        if completed.returncode == 0:
            return True
        if completed.returncode == SSH_TRANSPORT_FAILURE:
            time.sleep(delay)
            delay = min(delay * 2, REMOTE_POLL_MAX_SECONDS)
            continue
        return True
    return False


def _probe_remote_executor_liveness(
    host: str,
    handshake: Mapping[str, Any],
    *,
    command_runner: CommandRunner | None = None,
) -> RemoteExecutorLiveness:
    """Inspect target-side ``/proc`` identity without sending signals."""
    pid = handshake.get("executor_pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return RemoteExecutorLiveness("dead", "remote executor pid is missing")
    identity = handshake.get("executor_identity")
    if not isinstance(identity, str) or not identity:
        return RemoteExecutorLiveness("unknown", "remote executor identity is missing")
    runner = subprocess.run if command_runner is None else command_runner
    completed = run_ssh(
        "remote_sudo_liveness_failed",
        runner,
        ssh_argv(host, liveness_command(pid, identity)),
        kwargs={
            "check": False,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "timeout": REMOTE_POLL_SSH_TIMEOUT_SECONDS,
        },
        raise_timeout=False,
    )
    if completed is None:
        return RemoteExecutorLiveness("unknown", "remote liveness probe timed out")
    if completed.returncode == 0:
        return RemoteExecutorLiveness("live", "remote process identity still matches")
    if completed.returncode == LIVENESS_DEAD:
        return RemoteExecutorLiveness(
            "dead", "remote process is missing or identity does not match"
        )
    if completed.returncode == SSH_TRANSPORT_FAILURE:
        return RemoteExecutorLiveness("unknown", "remote liveness SSH transport failed")
    if completed.returncode == LIVENESS_UNKNOWN:
        return RemoteExecutorLiveness(
            "unknown", "remote process exists but identity could not be verified"
        )
    return RemoteExecutorLiveness(
        "unknown", "remote process exists but identity could not be verified"
    )


__all__ = [
    "cleanup_remote_sudo",
    "wait_for_remote_sudo_ledger",
]
