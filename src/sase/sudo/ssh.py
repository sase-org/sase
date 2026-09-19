"""SSH relay for machine-targeted sudo authentication."""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, BinaryIO, Literal, TextIO, overload
from uuid import uuid4

from sase.dispatch.models import validate_ssh_target
from sase.dispatch.ssh_login_shell import remote_login_shell_command
from sase.notification_gates.models import GateError
from sase.sudo.ssh_cli import unavailable_remote_cli_message

CommandRunner = Callable[..., subprocess.CompletedProcess[Any]]

_CONTRACT_SCHEMA_VERSION = 1
_DETACHED_EXECUTION_CAPABILITY = "detached_execution"
_REMOTE_BASE = "/tmp"
_REMOTE_EXECUTOR_DEATH_GRACE_SECONDS = 1.0
_REMOTE_POLL_MAX_SECONDS = 2.0
_REMOTE_POLL_SECONDS = 0.25
_REMOTE_POLL_SSH_TIMEOUT_SECONDS = 5.0
_REMOTE_STAGE_SSH_TIMEOUT_SECONDS = 15.0
_REMOTE_STOP_GRACE_SECONDS = 5.0
_REMOTE_OUTPUT_CHUNK_BYTES = 64 * 1024
_SSH_TRANSPORT_FAILURE = 255
_STAGE_MKDIR_FAILED = 11
_STAGE_CHMOD_FAILED = 12
_STAGE_WRITE_FAILED = 13
_STAGE_REPLACE_FAILED = 14
_STAGE_CHMOD_FILE_FAILED = 15
_LIVENESS_DEAD = 1
_LIVENESS_UNKNOWN = 2
PRE_SPAWN_REMOTE_ERROR_CODES = frozenset(
    {
        "detach_unsupported",
        "invalid_ssh_target",
        "remote_sudo_contract_mismatch",
        "remote_sudo_stage_failed",
        "remote_sudo_unavailable",
        "ssh_unavailable",
    }
)


@dataclass(frozen=True)
class _RemoteSudoPaths:
    """Opaque target-side paths for one remote sudo attempt."""

    directory: str
    manifest: str
    ledger: str
    handshake: str
    log: str
    stop: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-safe representation for operation sidecars."""
        return {
            "directory": self.directory,
            "handshake": self.handshake,
            "ledger": self.ledger,
            "log": self.log,
            "manifest": self.manifest,
            "stop": self.stop,
        }


@dataclass(frozen=True)
class _RemoteSudoContract:
    """Target-side sudo exec contract advertised by ``sase sudo exec``."""

    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class _RemoteExecutorLiveness:
    """Three-way remote executor probe result."""

    classification: str
    reason: str


def allocate_remote_sudo_paths(*, base: str = _REMOTE_BASE) -> dict[str, str]:
    """Return a unique remote handoff path set under *base*."""
    return _remote_paths(base=base).to_dict()


def remote_supports_detached_execution(
    host: str,
    *,
    command_runner: CommandRunner | None = None,
) -> bool:
    """Return whether ``host`` advertises detached sudo execution."""
    runner = subprocess.run if command_runner is None else command_runner
    _require_ssh_target(host)
    contract = _probe_contract(host, command_runner=runner)
    return _DETACHED_EXECUTION_CAPABILITY in contract.capabilities


def run_remote_sudo(
    host: str,
    manifest: Mapping[str, Any],
    *,
    manifest_sha256: str,
    command_runner: CommandRunner | None = None,
    timeout_seconds: float | None = None,
    paths: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Authenticate and execute a sealed sudo manifest on ``host`` over SSH."""
    runner = subprocess.run if command_runner is None else command_runner
    _require_ssh_target(host)
    _probe_contract(host, command_runner=runner)
    remote_paths = _coerce_paths(paths)
    manifest_bytes = json.dumps(dict(manifest), sort_keys=True).encode("utf-8") + b"\n"
    staged = False
    finished = False
    try:
        _stage_manifest(
            host,
            remote_paths,
            manifest_bytes,
            command_runner=runner,
        )
        staged = True
        _run_target_exec(
            host,
            remote_paths,
            manifest_sha256=manifest_sha256,
            command_runner=runner,
            timeout_seconds=timeout_seconds,
        )
        ledger = _fetch_ledger(host, remote_paths.ledger, command_runner=runner)
        finished = True
        return ledger
    finally:
        if (not staged) or finished:
            _cleanup(host, remote_paths, command_runner=runner)


def run_remote_sudo_detached(
    host: str,
    manifest: Mapping[str, Any],
    *,
    manifest_sha256: str,
    command_runner: CommandRunner | None = None,
    timeout_seconds: float | None = None,
    paths: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Authenticate on the remote TTY and start a remote detached executor."""
    runner = subprocess.run if command_runner is None else command_runner
    _require_ssh_target(host)
    contract = _probe_contract(host, command_runner=runner)
    if _DETACHED_EXECUTION_CAPABILITY not in contract.capabilities:
        raise GateError(
            "detach_unsupported",
            "ssh",
            "target sudo exec does not advertise detached_execution",
        )
    remote_paths = _coerce_paths(paths)
    manifest_bytes = json.dumps(dict(manifest), sort_keys=True).encode("utf-8") + b"\n"
    staged = False
    try:
        _stage_manifest(
            host,
            remote_paths,
            manifest_bytes,
            command_runner=runner,
        )
        staged = True
        _run_target_exec_detached(
            host,
            remote_paths,
            manifest_sha256=manifest_sha256,
            command_runner=runner,
            timeout_seconds=timeout_seconds,
        )
        handshake = _fetch_json_file_optional(
            host,
            remote_paths.handshake,
            command_runner=runner,
        )
        if handshake is not None:
            return handshake, remote_paths.to_dict()
        ledger = _fetch_json_file_optional(
            host,
            remote_paths.ledger,
            command_runner=runner,
        )
        if ledger is not None:
            _cleanup(host, remote_paths, command_runner=runner)
            return ledger, remote_paths.to_dict()
        raise GateError(
            "remote_sudo_startup_unresolved",
            "ssh",
            (
                "remote sudo exec finished without a handshake or ledger; "
                "the gate remains pending"
            ),
        )
    except Exception:
        if not staged:
            _cleanup(host, remote_paths, command_runner=runner)
        raise


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
    _require_ssh_target(host)
    paths = _paths_from_payload(paths_payload)
    timeout = 330.0 if timeout_seconds is None else max(0.0, float(timeout_seconds))
    deadline = time.monotonic() + timeout
    stop_deadline: float | None = None
    offset = 0
    delay = _REMOTE_POLL_SECONDS
    output_dest = sys.stdout if dest is None else dest

    def _on_stop(_signum: int, _frame: object | None) -> None:
        nonlocal stop_deadline
        _write_remote_stop(host, paths, command_runner=runner)
        if stop_deadline is None:
            stop_deadline = time.monotonic() + _REMOTE_STOP_GRACE_SECONDS

    previous_term = signal.getsignal(signal.SIGTERM)
    previous_int = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)
    try:
        while True:
            offset = _copy_remote_output_log(
                host,
                paths.log,
                offset=offset,
                dest=output_dest,
                command_runner=runner,
            )
            ledger = _fetch_json_file_optional(
                host,
                paths.ledger,
                command_runner=runner,
                timeout=_REMOTE_POLL_SSH_TIMEOUT_SECONDS,
            )
            if ledger is not None:
                _copy_remote_output_log(
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
                death_deadline = time.monotonic() + _REMOTE_EXECUTOR_DEATH_GRACE_SECONDS
                while time.monotonic() < death_deadline:
                    offset = _copy_remote_output_log(
                        host,
                        paths.log,
                        offset=offset,
                        dest=output_dest,
                        command_runner=runner,
                    )
                    ledger = _fetch_json_file_optional(
                        host,
                        paths.ledger,
                        command_runner=runner,
                        timeout=_REMOTE_POLL_SSH_TIMEOUT_SECONDS,
                    )
                    if ledger is not None:
                        _copy_remote_output_log(
                            host,
                            paths.log,
                            offset=offset,
                            dest=output_dest,
                            command_runner=runner,
                        )
                        return ledger
                    time.sleep(_REMOTE_POLL_SECONDS)
                raise GateError(
                    "executor_died",
                    "sudo.finalize",
                    (
                        "remote sudo executor exited without a ledger; "
                        "the gate remains pending"
                    ),
                )
            delay = _backoff_sleep(delay, deadline)
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
        _require_ssh_target(host)
        paths = _paths_from_payload(paths_payload)
    except GateError:
        return True
    delay = _REMOTE_POLL_SECONDS
    for _attempt in range(3):
        completed = _run_ssh(
            "remote_sudo_cleanup_failed",
            runner,
            _ssh_argv(
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
                "timeout": _REMOTE_POLL_SSH_TIMEOUT_SECONDS,
            },
            raise_timeout=False,
        )
        if completed is None:
            time.sleep(delay)
            delay = min(delay * 2, _REMOTE_POLL_MAX_SECONDS)
            continue
        if completed.returncode == 0:
            return True
        if completed.returncode == _SSH_TRANSPORT_FAILURE:
            time.sleep(delay)
            delay = min(delay * 2, _REMOTE_POLL_MAX_SECONDS)
            continue
        return True
    return False


def _probe_remote_executor_liveness(
    host: str,
    handshake: Mapping[str, Any],
    *,
    command_runner: CommandRunner | None = None,
) -> _RemoteExecutorLiveness:
    """Inspect target-side ``/proc`` identity without sending signals."""
    pid = handshake.get("executor_pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return _RemoteExecutorLiveness("dead", "remote executor pid is missing")
    identity = handshake.get("executor_identity")
    if not isinstance(identity, str) or not identity:
        return _RemoteExecutorLiveness("unknown", "remote executor identity is missing")
    runner = subprocess.run if command_runner is None else command_runner
    completed = _run_ssh(
        "remote_sudo_liveness_failed",
        runner,
        _ssh_argv(host, _liveness_command(pid, identity)),
        kwargs={
            "check": False,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "timeout": _REMOTE_POLL_SSH_TIMEOUT_SECONDS,
        },
        raise_timeout=False,
    )
    if completed is None:
        return _RemoteExecutorLiveness("unknown", "remote liveness probe timed out")
    if completed.returncode == 0:
        return _RemoteExecutorLiveness("live", "remote process identity still matches")
    if completed.returncode == _LIVENESS_DEAD:
        return _RemoteExecutorLiveness(
            "dead", "remote process is missing or identity does not match"
        )
    if completed.returncode == _SSH_TRANSPORT_FAILURE:
        return _RemoteExecutorLiveness(
            "unknown", "remote liveness SSH transport failed"
        )
    if completed.returncode == _LIVENESS_UNKNOWN:
        return _RemoteExecutorLiveness(
            "unknown", "remote process exists but identity could not be verified"
        )
    return _RemoteExecutorLiveness(
        "unknown", "remote process exists but identity could not be verified"
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


def _encode_target_sase_command(*argv: str) -> str:
    """Return a login-shell remote command for a target-side ``sase`` argv."""
    if not argv:
        raise GateError(
            "invalid_sudo_finalize",
            "ssh",
            "remote sudo command must not be empty",
        )
    return remote_login_shell_command(argv)


def _require_ssh_target(host: str) -> None:
    try:
        validate_ssh_target(host)
    except ValueError as exc:
        raise GateError("invalid_ssh_target", "ssh_target", str(exc)) from exc


def _ssh_argv(host: str, remote_command: str, *, tty: bool = False) -> list[str]:
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
def _authentication_ssh_stdio(host: str) -> Iterator[dict[str, Any]]:
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


def _probe_contract(host: str, *, command_runner: CommandRunner) -> _RemoteSudoContract:
    completed = _run_ssh(
        "remote_sudo_unavailable",
        command_runner,
        _ssh_argv(
            host,
            _encode_target_sase_command("sase", "sudo", "exec", "--contract"),
        ),
        kwargs={
            "check": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "timeout": _REMOTE_POLL_SSH_TIMEOUT_SECONDS,
        },
    )
    if completed.returncode != 0:
        raise GateError(
            "remote_sudo_unavailable",
            "ssh",
            unavailable_remote_cli_message(host, completed),
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise GateError(
            "remote_sudo_contract_mismatch",
            "ssh",
            "target sudo contract probe did not return JSON",
        ) from exc
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema_version") != _CONTRACT_SCHEMA_VERSION
    ):
        raise GateError(
            "remote_sudo_contract_mismatch",
            "ssh",
            "target sudo contract version is not supported",
        )
    capabilities = payload.get("capabilities")
    return _RemoteSudoContract(
        capabilities=tuple(
            item for item in capabilities or () if isinstance(item, str) and item
        )
        if isinstance(capabilities, list)
        else (),
    )


def _stage_manifest(
    host: str,
    paths: _RemoteSudoPaths,
    manifest_bytes: bytes,
    *,
    command_runner: CommandRunner,
) -> None:
    directory = shlex.quote(paths.directory)
    manifest = shlex.quote(paths.manifest)
    temporary = shlex.quote(f"{paths.manifest}.tmp")
    remote = (
        f"mkdir -p -m 700 {directory} || exit {_STAGE_MKDIR_FAILED}; "
        f"chmod 700 {directory} || exit {_STAGE_CHMOD_FAILED}; "
        f"umask 077; "
        f"cat > {temporary} || {{ rm -f {temporary}; exit {_STAGE_WRITE_FAILED}; }}; "
        f"mv {temporary} {manifest} || "
        f"{{ rm -f {temporary}; exit {_STAGE_REPLACE_FAILED}; }}; "
        f"chmod 600 {manifest} || exit {_STAGE_CHMOD_FILE_FAILED}"
    )
    completed = _run_ssh(
        "remote_sudo_stage_failed",
        command_runner,
        _ssh_argv(host, remote),
        kwargs={
            "input": manifest_bytes,
            "check": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "timeout": _REMOTE_STAGE_SSH_TIMEOUT_SECONDS,
        },
    )
    if completed.returncode == 0:
        return
    step = {
        _STAGE_MKDIR_FAILED: "create the remote handoff directory",
        _STAGE_CHMOD_FAILED: "set remote handoff directory permissions",
        _STAGE_WRITE_FAILED: "write the remote sudo manifest",
        _STAGE_REPLACE_FAILED: "replace the remote sudo manifest",
        _STAGE_CHMOD_FILE_FAILED: "set remote sudo manifest permissions",
    }.get(completed.returncode, "stage the remote sudo manifest")
    raise GateError(
        "remote_sudo_stage_failed",
        "ssh",
        f"could not {step} on {host!r}",
    )


def _run_target_exec(
    host: str,
    paths: _RemoteSudoPaths,
    *,
    manifest_sha256: str,
    command_runner: CommandRunner,
    timeout_seconds: float | None,
) -> None:
    remote = _encode_target_sase_command(
        "sase",
        "sudo",
        "exec",
        "--manifest",
        paths.manifest,
        "--expected-sha256",
        manifest_sha256,
        "--ledger",
        paths.ledger,
    )
    with _authentication_ssh_stdio(host) as stdio:
        completed = _run_ssh(
            "remote_sudo_exec_failed",
            command_runner,
            _ssh_argv(host, remote, tty=True),
            kwargs={
                "check": False,
                **stdio,
                "text": True,
                "timeout": timeout_seconds,
            },
        )
    if completed.returncode not in {0, 10, 11, 12, 14}:
        raise GateError(
            "remote_sudo_exec_failed",
            "ssh",
            f"remote sudo target exited {completed.returncode}; gate remains pending",
        )


def _run_target_exec_detached(
    host: str,
    paths: _RemoteSudoPaths,
    *,
    manifest_sha256: str,
    command_runner: CommandRunner,
    timeout_seconds: float | None,
) -> None:
    remote = _encode_target_sase_command(
        "sase",
        "sudo",
        "exec",
        "--detach",
        "--manifest",
        paths.manifest,
        "--expected-sha256",
        manifest_sha256,
        "--handshake",
        paths.handshake,
        "--ledger",
        paths.ledger,
    )
    with _authentication_ssh_stdio(host) as stdio:
        completed = _run_ssh(
            "remote_sudo_exec_failed",
            command_runner,
            _ssh_argv(host, remote, tty=True),
            kwargs={
                "check": False,
                **stdio,
                "text": True,
                "timeout": timeout_seconds,
            },
        )
    if completed.returncode not in {0, 10, 11, 12, 14}:
        raise GateError(
            "remote_sudo_exec_failed",
            "ssh",
            f"remote sudo target exited {completed.returncode}; gate remains pending",
        )


def _fetch_ledger(
    host: str,
    path: str,
    *,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    completed = _run_ssh(
        "remote_sudo_ledger_missing",
        command_runner,
        _ssh_argv(host, _encode_ssh_remote_command("cat", path)),
        kwargs={
            "check": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "timeout": _REMOTE_POLL_SSH_TIMEOUT_SECONDS,
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


def _fetch_json_file_optional(
    host: str,
    path: str,
    *,
    command_runner: CommandRunner,
    timeout: float | None = None,
) -> dict[str, Any] | None:
    completed = _run_ssh(
        "remote_sudo_file_missing",
        command_runner,
        _ssh_argv(host, _encode_ssh_remote_command("cat", path)),
        kwargs={
            "check": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "timeout": _REMOTE_POLL_SSH_TIMEOUT_SECONDS if timeout is None else timeout,
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


def _copy_remote_output_log(
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
        + f" {shlex.quote(path)} {offset} {_REMOTE_OUTPUT_CHUNK_BYTES}"
    )
    completed = _run_ssh(
        "remote_sudo_output_failed",
        command_runner,
        _ssh_argv(host, remote),
        kwargs={
            "check": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.DEVNULL,
            "timeout": _REMOTE_POLL_SSH_TIMEOUT_SECONDS,
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


def _cleanup(
    host: str,
    paths: _RemoteSudoPaths,
    *,
    command_runner: CommandRunner,
) -> None:
    cleanup_remote_sudo(host, paths.to_dict(), command_runner=command_runner)


@overload
def _run_ssh(
    code: str,
    command_runner: CommandRunner,
    argv: list[str],
    *,
    kwargs: dict[str, Any],
    raise_timeout: Literal[True] = True,
) -> subprocess.CompletedProcess[Any]: ...


@overload
def _run_ssh(
    code: str,
    command_runner: CommandRunner,
    argv: list[str],
    *,
    kwargs: dict[str, Any],
    raise_timeout: Literal[False],
) -> subprocess.CompletedProcess[Any] | None: ...


def _run_ssh(
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


def _remote_paths(*, base: str = _REMOTE_BASE) -> _RemoteSudoPaths:
    token = uuid4().hex
    directory = f"{base.rstrip('/')}/sase-sudo-{token}"
    return _RemoteSudoPaths(
        directory=directory,
        handshake=f"{directory}/handshake.json",
        ledger=f"{directory}/ledger.json",
        log=f"{directory}/output.log",
        manifest=f"{directory}/manifest.json",
        stop=f"{directory}/stop",
    )


def _coerce_paths(payload: Mapping[str, Any] | None) -> _RemoteSudoPaths:
    if payload is None:
        return _remote_paths()
    return _paths_from_payload(payload)


def _paths_from_payload(payload: Mapping[str, Any]) -> _RemoteSudoPaths:
    try:
        directory = str(payload["directory"])
        handshake = str(payload["handshake"])
        ledger = str(payload["ledger"])
        log = str(payload["log"])
        manifest = str(payload["manifest"])
        stop = str(payload["stop"])
    except KeyError as exc:
        raise GateError(
            "invalid_sudo_finalize",
            "remote.paths",
            f"remote sudo path payload is missing {exc.args[0]}",
        ) from exc
    if not all((directory, handshake, ledger, log, manifest, stop)):
        raise GateError(
            "invalid_sudo_finalize",
            "remote.paths",
            "remote sudo paths must be non-empty strings",
        )
    return _RemoteSudoPaths(
        directory=directory,
        handshake=handshake,
        ledger=ledger,
        log=log,
        manifest=manifest,
        stop=stop,
    )


def _liveness_command(pid: int, identity: str) -> str:
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


def _write_remote_stop(
    host: str,
    paths: _RemoteSudoPaths,
    *,
    command_runner: CommandRunner,
) -> None:
    remote = f"umask 077; : > {shlex.quote(paths.stop)}"
    _run_ssh(
        "remote_sudo_stop_failed",
        command_runner,
        _ssh_argv(host, remote),
        kwargs={
            "check": False,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "timeout": _REMOTE_POLL_SSH_TIMEOUT_SECONDS,
        },
        raise_timeout=False,
    )


def _backoff_sleep(delay: float, deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return delay
    time.sleep(min(delay, remaining))
    return min(max(delay * 2.0, delay), _REMOTE_POLL_MAX_SECONDS)


__all__ = [
    "CommandRunner",
    "PRE_SPAWN_REMOTE_ERROR_CODES",
    "allocate_remote_sudo_paths",
    "cleanup_remote_sudo",
    "remote_supports_detached_execution",
    "run_remote_sudo",
    "run_remote_sudo_detached",
    "wait_for_remote_sudo_ledger",
]
