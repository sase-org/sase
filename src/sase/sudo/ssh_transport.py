"""Low-level SSH transport for machine-targeted sudo."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, BinaryIO, Literal, TextIO, overload

from sase.dispatch.models import validate_ssh_target
from sase.dispatch.ssh_login_shell import remote_login_shell_command
from sase.notification_gates.models import GateError
from sase.sudo.ssh_defs import (
    REMOTE_OUTPUT_CHUNK_BYTES,
    REMOTE_POLL_MAX_SECONDS,
    REMOTE_POLL_SSH_TIMEOUT_SECONDS,
    CommandRunner,
    RemoteSudoPaths,
)


def _encode_ssh_remote_command(*argv: str) -> str:
    """Return one remote command string with shell-quoted arguments."""
    if not argv:
        raise GateError(
            "invalid_sudo_finalize",
            "ssh",
            "remote sudo command must not be empty",
        )
    return shlex.join(argv)


def encode_target_sase_command(*argv: str) -> str:
    """Return a login-shell remote command for a target-side ``sase`` argv."""
    if not argv:
        raise GateError(
            "invalid_sudo_finalize",
            "ssh",
            "remote sudo command must not be empty",
        )
    return remote_login_shell_command(argv)


def require_ssh_target(host: str) -> None:
    try:
        validate_ssh_target(host)
    except ValueError as exc:
        raise GateError("invalid_ssh_target", "ssh_target", str(exc)) from exc


def ssh_argv(host: str, remote_command: str, *, tty: bool = False) -> list[str]:
    argv = ["ssh"]
    if tty:
        argv.append("-t")
    argv.append(host)
    argv.append(remote_command)
    return argv


def _open_controlling_tty() -> int:
    """Open the controlling terminal for authentication SSH stdio."""
    flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    return os.open("/dev/tty", flags)


def _tty_required() -> GateError:
    return GateError(
        "tty_required",
        "ssh",
        "remote sudo authentication requires a controlling TTY; "
        "the gate remains pending",
    )


@contextmanager
def authentication_ssh_stdio(host: str) -> Iterator[dict[str, Any]]:
    """Attach authentication ``ssh -t`` to ``/dev/tty``, not inherited pipes."""
    try:
        fd = _open_controlling_tty()
    except OSError as exc:
        raise _tty_required() from exc
    try:
        try:
            os.write(fd, f"sase sudo: authenticate on {host}\n".encode())
        except OSError as exc:
            raise _tty_required() from exc
        yield {"stdin": fd, "stdout": fd, "stderr": fd}
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


@overload
def run_ssh(
    code: str,
    command_runner: CommandRunner,
    argv: list[str],
    *,
    kwargs: dict[str, Any],
    raise_timeout: Literal[True] = True,
) -> subprocess.CompletedProcess[Any]: ...


@overload
def run_ssh(
    code: str,
    command_runner: CommandRunner,
    argv: list[str],
    *,
    kwargs: dict[str, Any],
    raise_timeout: Literal[False],
) -> subprocess.CompletedProcess[Any] | None: ...


def run_ssh(
    code: str,
    command_runner: CommandRunner,
    argv: list[str],
    *,
    kwargs: dict[str, Any],
    raise_timeout: bool = True,
) -> subprocess.CompletedProcess[Any] | None:
    try:
        return command_runner(argv, **kwargs)
    except FileNotFoundError as exc:
        raise GateError(
            "ssh_unavailable",
            "ssh",
            "ssh is not installed or not on PATH",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        if not raise_timeout:
            return None
        raise GateError(
            "timeout",
            "ssh",
            "remote sudo SSH operation timed out; gate remains pending",
        ) from exc
    except OSError as exc:
        raise GateError(
            code,
            "ssh",
            f"remote sudo SSH operation failed: {exc}",
        ) from exc


def fetch_ledger(
    host: str,
    path: str,
    *,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    completed = run_ssh(
        "remote_sudo_ledger_missing",
        command_runner,
        ssh_argv(host, _encode_ssh_remote_command("cat", path)),
        kwargs={
            "check": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "timeout": REMOTE_POLL_SSH_TIMEOUT_SECONDS,
        },
    )
    if completed.returncode != 0:
        raise GateError(
            "remote_sudo_ledger_missing",
            "ssh",
            "target did not produce a sudo ledger; gate remains pending",
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise GateError(
            "invalid_runner_output",
            "ssh",
            "remote sudo ledger must be JSON",
        ) from exc
    if not isinstance(value, dict):
        raise GateError(
            "invalid_runner_output",
            "ssh",
            "remote sudo ledger must be an object",
        )
    return value


def fetch_json_file_optional(
    host: str,
    path: str,
    *,
    command_runner: CommandRunner,
    timeout: float | None = None,
) -> dict[str, Any] | None:
    completed = run_ssh(
        "remote_sudo_file_missing",
        command_runner,
        ssh_argv(host, _encode_ssh_remote_command("cat", path)),
        kwargs={
            "check": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "timeout": REMOTE_POLL_SSH_TIMEOUT_SECONDS if timeout is None else timeout,
        },
        raise_timeout=False,
    )
    if completed is None or completed.returncode != 0:
        return None
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return dict(value) if isinstance(value, dict) else None


def copy_remote_output_log(
    host: str,
    path: str,
    *,
    offset: int,
    dest: BinaryIO | TextIO,
    command_runner: CommandRunner,
) -> int:
    if offset < 0:
        offset = 0
    remote = (
        "python3 -c "
        + shlex.quote(
            "import os,sys\n"
            "path,offset,limit=sys.argv[1],int(sys.argv[2]),int(sys.argv[3])\n"
            "try:\n"
            "    fd=os.open(path, os.O_RDONLY)\n"
            "except FileNotFoundError:\n"
            "    raise SystemExit(0)\n"
            "except OSError:\n"
            "    raise SystemExit(2)\n"
            "try:\n"
            "    os.lseek(fd, offset, os.SEEK_SET)\n"
            "    data=os.read(fd, limit)\n"
            "finally:\n"
            "    os.close(fd)\n"
            "sys.stdout.buffer.write(data)\n"
        )
        + f" {shlex.quote(path)} {offset} {REMOTE_OUTPUT_CHUNK_BYTES}"
    )
    completed = run_ssh(
        "remote_sudo_output_failed",
        command_runner,
        ssh_argv(host, remote),
        kwargs={
            "check": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.DEVNULL,
            "timeout": REMOTE_POLL_SSH_TIMEOUT_SECONDS,
        },
        raise_timeout=False,
    )
    if completed is None or completed.returncode != 0:
        return offset
    chunk = completed.stdout if isinstance(completed.stdout, bytes) else b""
    if isinstance(completed.stdout, str):
        chunk = completed.stdout.encode("utf-8")
    if chunk:
        _write_output_chunk(dest, chunk)
        _flush_output(dest)
        offset += len(chunk)
    return offset


def liveness_command(pid: int, identity: str) -> str:
    return (
        f"pid={shlex.quote(str(pid))}; identity={shlex.quote(identity)}; "
        'proc="/proc/$pid"; '
        'if [ ! -e "$proc" ]; then exit 1; fi; '
        'stat_file="$proc/stat"; '
        'if [ ! -r "$stat_file" ]; then exit 2; fi; '
        'boot="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)"; '
        'start="$(sed "s/^.*) //" "$stat_file" | awk \'{print $20}\')"; '
        'if [ -z "$boot" ] || [ -z "$start" ]; then exit 2; fi; '
        'current="${boot}:${start}"; '
        '[ "$current" = "$identity" ] || exit 1'
    )


def _write_output_chunk(dest: BinaryIO | TextIO, chunk: bytes) -> None:
    buffer = getattr(dest, "buffer", None)
    if buffer is not None:
        buffer.write(chunk)
        return
    write = getattr(dest, "write", None)
    if write is None:
        return
    try:
        write(chunk)
    except TypeError:
        write(chunk.decode("utf-8", errors="replace"))


def _flush_output(dest: BinaryIO | TextIO) -> None:
    buffer = getattr(dest, "buffer", None)
    if buffer is not None:
        buffer.flush()
        return
    flush = getattr(dest, "flush", None)
    if flush is not None:
        flush()


def write_remote_stop(
    host: str,
    paths: RemoteSudoPaths,
    *,
    command_runner: CommandRunner,
) -> None:
    remote = f"umask 077; : > {shlex.quote(paths.stop)}"
    run_ssh(
        "remote_sudo_stop_failed",
        command_runner,
        ssh_argv(host, remote),
        kwargs={
            "check": False,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "timeout": REMOTE_POLL_SSH_TIMEOUT_SECONDS,
        },
        raise_timeout=False,
    )


def backoff_sleep(delay: float, deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return delay
    time.sleep(min(delay, remaining))
    return min(max(delay * 2.0, delay), REMOTE_POLL_MAX_SECONDS)


__all__ = [
    "authentication_ssh_stdio",
    "backoff_sleep",
    "copy_remote_output_log",
    "encode_target_sase_command",
    "fetch_json_file_optional",
    "fetch_ledger",
    "liveness_command",
    "require_ssh_target",
    "run_ssh",
    "ssh_argv",
    "write_remote_stop",
]
