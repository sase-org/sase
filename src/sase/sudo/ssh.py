"""SSH relay for machine-targeted sudo authentication."""

from __future__ import annotations

import json
import signal
import shlex
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sase.dispatch.models import validate_ssh_target
from sase.notification_gates.models import GateError

CommandRunner = Callable[..., subprocess.CompletedProcess[Any]]

_CONTRACT_SCHEMA_VERSION = 1
_DETACHED_EXECUTION_CAPABILITY = "detached_execution"
_REMOTE_BASE = "/tmp"
_REMOTE_EXECUTOR_DEATH_GRACE_SECONDS = 1.0
_REMOTE_POLL_SECONDS = 0.25
_REMOTE_POLL_SSH_TIMEOUT_SECONDS = 5.0
_REMOTE_STOP_GRACE_SECONDS = 5.0
_SSH_TRANSPORT_FAILURE = 255


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


def remote_supports_detached_execution(
    host: str,
    *,
    command_runner: CommandRunner = subprocess.run,
) -> bool:
    """Return whether ``host`` advertises detached sudo execution."""
    try:
        validate_ssh_target(host)
    except ValueError as exc:
        raise GateError("invalid_ssh_target", "ssh_target", str(exc)) from exc
    contract = _probe_contract(host, command_runner=command_runner)
    return _DETACHED_EXECUTION_CAPABILITY in contract.capabilities


def run_remote_sudo(
    host: str,
    manifest: Mapping[str, Any],
    *,
    manifest_sha256: str,
    command_runner: CommandRunner = subprocess.run,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    """Authenticate and execute a sealed sudo manifest on ``host`` over SSH."""
    try:
        validate_ssh_target(host)
    except ValueError as exc:
        raise GateError("invalid_ssh_target", "ssh_target", str(exc)) from exc
    _probe_contract(host, command_runner=command_runner)
    paths = _remote_paths()
    manifest_bytes = json.dumps(dict(manifest), sort_keys=True).encode("utf-8") + b"\n"
    try:
        _stage_manifest(
            host,
            paths,
            manifest_bytes,
            command_runner=command_runner,
        )
        _run_target_exec(
            host,
            paths,
            manifest_sha256=manifest_sha256,
            command_runner=command_runner,
            timeout_seconds=timeout_seconds,
        )
        return _fetch_ledger(host, paths.ledger, command_runner=command_runner)
    finally:
        _cleanup(host, paths, command_runner=command_runner)


def run_remote_sudo_detached(
    host: str,
    manifest: Mapping[str, Any],
    *,
    manifest_sha256: str,
    command_runner: CommandRunner = subprocess.run,
    timeout_seconds: float | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Authenticate on the remote TTY and start a remote detached executor."""
    try:
        validate_ssh_target(host)
    except ValueError as exc:
        raise GateError("invalid_ssh_target", "ssh_target", str(exc)) from exc
    contract = _probe_contract(host, command_runner=command_runner)
    if _DETACHED_EXECUTION_CAPABILITY not in contract.capabilities:
        raise GateError(
            "detach_unsupported",
            "ssh",
            "target sudo exec does not advertise detached_execution",
        )
    paths = _remote_paths()
    manifest_bytes = json.dumps(dict(manifest), sort_keys=True).encode("utf-8") + b"\n"
    started = False
    try:
        _stage_manifest(
            host,
            paths,
            manifest_bytes,
            command_runner=command_runner,
        )
        _run_target_exec_detached(
            host,
            paths,
            manifest_sha256=manifest_sha256,
            command_runner=command_runner,
            timeout_seconds=timeout_seconds,
        )
        handshake = _fetch_json_file_optional(
            host,
            paths.handshake,
            command_runner=command_runner,
        )
        if handshake is not None:
            started = True
            return handshake, paths.to_dict()
        ledger = _fetch_ledger(host, paths.ledger, command_runner=command_runner)
        return ledger, paths.to_dict()
    finally:
        if not started:
            _cleanup(host, paths, command_runner=command_runner)


def wait_for_remote_sudo_ledger(
    host: str,
    paths_payload: Mapping[str, Any],
    *,
    handshake: Mapping[str, Any],
    command_runner: CommandRunner = subprocess.run,
    timeout_seconds: float | None,
) -> dict[str, Any]:
    """Poll a remote detached sudo executor until its ledger is readable."""
    try:
        validate_ssh_target(host)
    except ValueError as exc:
        raise GateError("invalid_ssh_target", "ssh_target", str(exc)) from exc
    paths = _paths_from_payload(paths_payload)
    timeout = 330.0 if timeout_seconds is None else max(0.0, float(timeout_seconds))
    deadline = time.monotonic() + timeout
    stop_deadline: float | None = None

    def _on_stop(_signum: int, _frame: object | None) -> None:
        nonlocal stop_deadline
        _write_remote_stop(host, paths, command_runner=command_runner)
        if stop_deadline is None:
            stop_deadline = time.monotonic() + _REMOTE_STOP_GRACE_SECONDS

    previous_term = signal.getsignal(signal.SIGTERM)
    previous_int = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)
    try:
        while True:
            ledger = _fetch_json_file_optional(
                host,
                paths.ledger,
                command_runner=command_runner,
                timeout=_REMOTE_POLL_SSH_TIMEOUT_SECONDS,
            )
            if ledger is not None:
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
            live = _remote_executor_is_live(
                host,
                handshake,
                command_runner=command_runner,
            )
            if live is False:
                death_deadline = time.monotonic() + _REMOTE_EXECUTOR_DEATH_GRACE_SECONDS
                while time.monotonic() < death_deadline:
                    ledger = _fetch_json_file_optional(
                        host,
                        paths.ledger,
                        command_runner=command_runner,
                        timeout=_REMOTE_POLL_SSH_TIMEOUT_SECONDS,
                    )
                    if ledger is not None:
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
            time.sleep(_REMOTE_POLL_SECONDS)
    finally:
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)


def cleanup_remote_sudo(
    host: str,
    paths_payload: Mapping[str, Any],
    *,
    command_runner: CommandRunner = subprocess.run,
) -> None:
    """Best-effort removal of remote handoff files."""
    _cleanup(host, _paths_from_payload(paths_payload), command_runner=command_runner)


def _probe_contract(host: str, *, command_runner: CommandRunner) -> _RemoteSudoContract:
    completed = _run_ssh(
        "remote_sudo_unavailable",
        command_runner,
        ["ssh", host, "sase", "sudo", "exec", "--contract"],
        kwargs={
            "check": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        },
    )
    if completed.returncode != 0:
        raise GateError(
            "remote_sudo_unavailable",
            "ssh",
            f"could not reach sudo target {host!r} or target CLI is missing",
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
    remote = (
        f"mkdir -p -m 700 {shlex.quote(paths.directory)}; "
        f"umask 077; cat > {shlex.quote(paths.manifest)}"
    )
    completed = _run_ssh(
        "remote_sudo_stage_failed",
        command_runner,
        ["ssh", host, "sh", "-c", remote],
        kwargs={
            "input": manifest_bytes,
            "check": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        },
    )
    if completed.returncode != 0:
        raise GateError(
            "remote_sudo_stage_failed",
            "ssh",
            f"could not stage sudo manifest on {host!r}",
        )


def _run_target_exec(
    host: str,
    paths: _RemoteSudoPaths,
    *,
    manifest_sha256: str,
    command_runner: CommandRunner,
    timeout_seconds: float | None,
) -> None:
    remote_argv = [
        "sase",
        "sudo",
        "exec",
        "--manifest",
        paths.manifest,
        "--expected-sha256",
        manifest_sha256,
        "--ledger",
        paths.ledger,
    ]
    completed = _run_ssh(
        "remote_sudo_exec_failed",
        command_runner,
        ["ssh", "-t", host, *remote_argv],
        kwargs={
            "check": False,
            "stderr": None,
            "stdout": None,
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
    remote_argv = [
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
    ]
    completed = _run_ssh(
        "remote_sudo_exec_failed",
        command_runner,
        ["ssh", "-t", host, *remote_argv],
        kwargs={
            "check": False,
            "stderr": None,
            "stdout": None,
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
        ["ssh", host, "cat", path],
        kwargs={
            "check": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
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
    try:
        completed = _run_ssh(
            "remote_sudo_file_missing",
            command_runner,
            ["ssh", host, "cat", path],
            kwargs={
                "check": False,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                **({} if timeout is None else {"timeout": timeout}),
            },
        )
    except GateError:
        return None
    if completed.returncode != 0:
        return None
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    return dict(value) if isinstance(value, dict) else None


def _cleanup(
    host: str,
    paths: _RemoteSudoPaths,
    *,
    command_runner: CommandRunner,
) -> None:
    try:
        command_runner(
            ["ssh", host, "sh", "-c", f"rm -rf {shlex.quote(paths.directory)}"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return


def _run_ssh(
    code: str,
    command_runner: CommandRunner,
    argv: list[str],
    *,
    kwargs: dict[str, Any],
) -> subprocess.CompletedProcess[Any]:
    try:
        return command_runner(argv, **kwargs)
    except FileNotFoundError as exc:
        raise GateError(
            "ssh_unavailable",
            "ssh",
            "ssh is not installed or not on PATH",
        ) from exc
    except subprocess.TimeoutExpired as exc:
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


def _remote_paths() -> _RemoteSudoPaths:
    token = uuid4().hex
    directory = f"{_REMOTE_BASE}/sase-sudo-{token}"
    return _RemoteSudoPaths(
        directory=directory,
        handshake=f"{directory}/handshake.json",
        ledger=f"{directory}/ledger.json",
        log=f"{directory}/output.log",
        manifest=f"{directory}/manifest.json",
        stop=f"{directory}/stop",
    )


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


def _remote_executor_is_live(
    host: str,
    handshake: Mapping[str, Any],
    *,
    command_runner: CommandRunner,
) -> bool | None:
    pid = handshake.get("executor_pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    identity = handshake.get("executor_identity")
    script = (
        'pid="$1"; identity="$2"; '
        'kill -0 "$pid" 2>/dev/null || exit 1; '
        'case "$identity" in *:*) ;; *) exit 0;; esac; '
        'stat_file="/proc/$pid/stat"; '
        '[ -r "$stat_file" ] || exit 0; '
        'boot="$(cat /proc/sys/kernel/random/boot_id 2>/dev/null || true)"; '
        'start="$(sed "s/^.*) //" "$stat_file" | awk \'{print $20}\')"; '
        '[ -n "$start" ] || exit 0; '
        'current="${boot}:${start}"; '
        '[ "$current" = "$identity" ]'
    )
    try:
        completed = _run_ssh(
            "remote_sudo_liveness_failed",
            command_runner,
            ["ssh", host, "sh", "-c", script, "sh", str(pid), str(identity or "")],
            kwargs={
                "check": False,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "timeout": _REMOTE_POLL_SSH_TIMEOUT_SECONDS,
            },
        )
    except GateError:
        return None
    if completed.returncode == 0:
        return True
    if completed.returncode == _SSH_TRANSPORT_FAILURE:
        return None
    return False


def _write_remote_stop(
    host: str,
    paths: _RemoteSudoPaths,
    *,
    command_runner: CommandRunner,
) -> None:
    remote = f"umask 077; : > {shlex.quote(paths.stop)}"
    try:
        _run_ssh(
            "remote_sudo_stop_failed",
            command_runner,
            ["ssh", host, "sh", "-c", remote],
            kwargs={
                "check": False,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "timeout": _REMOTE_POLL_SSH_TIMEOUT_SECONDS,
            },
        )
    except GateError:
        return


__all__ = [
    "CommandRunner",
    "cleanup_remote_sudo",
    "remote_supports_detached_execution",
    "run_remote_sudo",
    "run_remote_sudo_detached",
    "wait_for_remote_sudo_ledger",
]
