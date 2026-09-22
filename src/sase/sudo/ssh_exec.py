"""Staging and execution of sealed sudo manifests on SSH targets."""

from __future__ import annotations

import json
import shlex
import subprocess
from collections.abc import Mapping
from typing import Any

from sase.notification_gates.models import GateError
from sase.sudo.ssh_cli import unavailable_remote_cli_message
from sase.sudo.ssh_defs import (
    CONTRACT_SCHEMA_VERSION,
    DETACHED_EXECUTION_CAPABILITY,
    REMOTE_POLL_SSH_TIMEOUT_SECONDS,
    REMOTE_STAGE_SSH_TIMEOUT_SECONDS,
    STAGE_CHMOD_FAILED,
    STAGE_CHMOD_FILE_FAILED,
    STAGE_MKDIR_FAILED,
    STAGE_REPLACE_FAILED,
    STAGE_WRITE_FAILED,
    CommandRunner,
    RemoteSudoContract,
    RemoteSudoPaths,
)
from sase.sudo.ssh_detached import cleanup_remote_sudo
from sase.sudo.ssh_paths import coerce_paths
from sase.sudo.ssh_transport import (
    authentication_ssh_stdio,
    encode_target_sase_command,
    fetch_json_file_optional,
    fetch_ledger,
    require_ssh_target,
    run_ssh,
    ssh_argv,
)


def remote_supports_detached_execution(
    host: str,
    *,
    command_runner: CommandRunner | None = None,
) -> bool:
    """Return whether ``host`` advertises detached sudo execution."""
    runner = subprocess.run if command_runner is None else command_runner
    require_ssh_target(host)
    contract = _probe_contract(host, command_runner=runner)
    return DETACHED_EXECUTION_CAPABILITY in contract.capabilities


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
    require_ssh_target(host)
    _probe_contract(host, command_runner=runner)
    remote_paths = coerce_paths(paths)
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
        ledger = fetch_ledger(host, remote_paths.ledger, command_runner=runner)
        finished = True
        return ledger
    finally:
        if (not staged) or finished:
            cleanup_remote_sudo(host, remote_paths.to_dict(), command_runner=runner)


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
    require_ssh_target(host)
    contract = _probe_contract(host, command_runner=runner)
    if DETACHED_EXECUTION_CAPABILITY not in contract.capabilities:
        raise GateError(
            "detach_unsupported",
            "ssh",
            "target sudo exec does not advertise detached_execution",
        )
    remote_paths = coerce_paths(paths)
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
        handshake = fetch_json_file_optional(
            host,
            remote_paths.handshake,
            command_runner=runner,
        )
        if handshake is not None:
            return handshake, remote_paths.to_dict()
        ledger = fetch_json_file_optional(
            host,
            remote_paths.ledger,
            command_runner=runner,
        )
        if ledger is not None:
            cleanup_remote_sudo(host, remote_paths.to_dict(), command_runner=runner)
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
            cleanup_remote_sudo(host, remote_paths.to_dict(), command_runner=runner)
        raise


def _probe_contract(host: str, *, command_runner: CommandRunner) -> RemoteSudoContract:
    completed = run_ssh(
        "remote_sudo_unavailable",
        command_runner,
        ssh_argv(
            host,
            encode_target_sase_command("sase", "sudo", "exec", "--contract"),
        ),
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
        or payload.get("schema_version") != CONTRACT_SCHEMA_VERSION
    ):
        raise GateError(
            "remote_sudo_contract_mismatch",
            "ssh",
            "target sudo contract version is not supported",
        )
    capabilities = payload.get("capabilities")
    return RemoteSudoContract(
        capabilities=tuple(
            item for item in capabilities or () if isinstance(item, str) and item
        )
        if isinstance(capabilities, list)
        else (),
    )


def _stage_manifest(
    host: str,
    paths: RemoteSudoPaths,
    manifest_bytes: bytes,
    *,
    command_runner: CommandRunner,
) -> None:
    directory = shlex.quote(paths.directory)
    manifest = shlex.quote(paths.manifest)
    temporary = shlex.quote(f"{paths.manifest}.tmp")
    remote = (
        f"mkdir -p -m 700 {directory} || exit {STAGE_MKDIR_FAILED}; "
        f"chmod 700 {directory} || exit {STAGE_CHMOD_FAILED}; "
        f"umask 077; "
        f"cat > {temporary} || {{ rm -f {temporary}; exit {STAGE_WRITE_FAILED}; }}; "
        f"mv {temporary} {manifest} || "
        f"{{ rm -f {temporary}; exit {STAGE_REPLACE_FAILED}; }}; "
        f"chmod 600 {manifest} || exit {STAGE_CHMOD_FILE_FAILED}"
    )
    completed = run_ssh(
        "remote_sudo_stage_failed",
        command_runner,
        ssh_argv(host, remote),
        kwargs={
            "input": manifest_bytes,
            "check": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "timeout": REMOTE_STAGE_SSH_TIMEOUT_SECONDS,
        },
    )
    if completed.returncode == 0:
        return
    step = {
        STAGE_MKDIR_FAILED: "create the remote handoff directory",
        STAGE_CHMOD_FAILED: "set remote handoff directory permissions",
        STAGE_WRITE_FAILED: "write the remote sudo manifest",
        STAGE_REPLACE_FAILED: "replace the remote sudo manifest",
        STAGE_CHMOD_FILE_FAILED: "set remote sudo manifest permissions",
    }.get(completed.returncode, "stage the remote sudo manifest")
    raise GateError(
        "remote_sudo_stage_failed",
        "ssh",
        f"could not {step} on {host!r}",
    )


def _run_target_exec(
    host: str,
    paths: RemoteSudoPaths,
    *,
    manifest_sha256: str,
    command_runner: CommandRunner,
    timeout_seconds: float | None,
) -> None:
    remote = encode_target_sase_command(
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
    with authentication_ssh_stdio(host) as stdio:
        completed = run_ssh(
            "remote_sudo_exec_failed",
            command_runner,
            ssh_argv(host, remote, tty=True),
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
    paths: RemoteSudoPaths,
    *,
    manifest_sha256: str,
    command_runner: CommandRunner,
    timeout_seconds: float | None,
) -> None:
    remote = encode_target_sase_command(
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
    with authentication_ssh_stdio(host) as stdio:
        completed = run_ssh(
            "remote_sudo_exec_failed",
            command_runner,
            ssh_argv(host, remote, tty=True),
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


__all__ = [
    "remote_supports_detached_execution",
    "run_remote_sudo",
    "run_remote_sudo_detached",
]
