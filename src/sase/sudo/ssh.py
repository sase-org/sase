"""SSH relay for machine-targeted sudo authentication."""

from __future__ import annotations

import json
import shlex
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sase.dispatch.models import validate_ssh_target
from sase.notification_gates.models import GateError

CommandRunner = Callable[..., subprocess.CompletedProcess[Any]]

_CONTRACT_SCHEMA_VERSION = 1
_REMOTE_BASE = "/tmp"


@dataclass(frozen=True)
class _RemoteSudoPaths:
    """Opaque target-side paths for one remote sudo attempt."""

    manifest: str
    ledger: str


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
            paths.manifest,
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


def _probe_contract(host: str, *, command_runner: CommandRunner) -> None:
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
    if not isinstance(payload, Mapping) or payload.get("schema_version") != (
        _CONTRACT_SCHEMA_VERSION
    ):
        raise GateError(
            "remote_sudo_contract_mismatch",
            "ssh",
            "target sudo contract version is not supported",
        )


def _stage_manifest(
    host: str,
    path: str,
    manifest_bytes: bytes,
    *,
    command_runner: CommandRunner,
) -> None:
    remote = f"umask 077; cat > {shlex.quote(path)}"
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


def _cleanup(
    host: str,
    paths: _RemoteSudoPaths,
    *,
    command_runner: CommandRunner,
) -> None:
    quoted = " ".join(shlex.quote(path) for path in (paths.manifest, paths.ledger))
    command_runner(
        ["ssh", host, "sh", "-c", f"rm -f {quoted}"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


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
    return _RemoteSudoPaths(
        manifest=f"{_REMOTE_BASE}/sase-sudo-{token}.manifest.json",
        ledger=f"{_REMOTE_BASE}/sase-sudo-{token}.ledger.json",
    )


__all__ = ["CommandRunner", "run_remote_sudo"]
