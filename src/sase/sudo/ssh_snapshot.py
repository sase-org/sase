"""Request-time and approval-time remote executable snapshots over SSH."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sase.notification_gates.models import GateError
from sase.sudo.snapshot import (
    SNAPSHOT_KIND,
    SNAPSHOT_SCHEMA_VERSION,
    ExecutableSnapshot,
)
from sase.sudo.ssh_defs import (
    EXECUTABLE_SNAPSHOT_CAPABILITY,
    REMOTE_POLL_SSH_TIMEOUT_SECONDS,
    CommandRunner,
)
from sase.sudo.ssh_exec import probe_remote_sudo_contract
from sase.sudo.ssh_transport import (
    encode_target_sase_command,
    require_ssh_target,
    run_ssh,
    ssh_argv,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_KNOWN_SNAPSHOT_ERRORS = frozenset(
    {"agent_writable_executable", "unsnapshotshotted_executable"}
)


@dataclass(frozen=True)
class _RemoteExecutableSnapshot:
    """Validated target-side snapshot of one or more executables."""

    host_facts: dict[str, Any]
    executables: tuple[ExecutableSnapshot, ...]

    def by_path(self) -> dict[str, ExecutableSnapshot]:
        return {item.path: item for item in self.executables}


def snapshot_remote_executables(
    host: str,
    paths: Sequence[str],
    *,
    command_runner: CommandRunner | None = None,
) -> _RemoteExecutableSnapshot:
    """Snapshot *paths* on *host* through ``sase sudo exec --snapshot``."""
    runner = subprocess.run if command_runner is None else command_runner
    require_ssh_target(host)
    unique_paths = _unique_paths(paths)
    try:
        contract = probe_remote_sudo_contract(host, command_runner=runner, batch=True)
    except GateError as exc:
        raise _remote_snapshot_unavailable(host, exc) from exc
    if EXECUTABLE_SNAPSHOT_CAPABILITY not in contract.capabilities:
        raise GateError(
            "remote_snapshot_unavailable",
            "ssh",
            f"upgrade sase on {host}",
        )
    remote = encode_target_sase_command(
        "sase",
        "sudo",
        "exec",
        *[item for path in unique_paths for item in ("--snapshot", path)],
    )
    try:
        completed = run_ssh(
            "remote_snapshot_unavailable",
            runner,
            ssh_argv(host, remote, batch=True),
            kwargs={
                "check": False,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "timeout": REMOTE_POLL_SSH_TIMEOUT_SECONDS,
            },
        )
    except GateError as exc:
        raise _remote_snapshot_unavailable(host, exc) from exc
    if completed.returncode != 0:
        raise GateError(
            "remote_snapshot_unavailable",
            "ssh",
            (
                f"could not snapshot executables on {host!r}; "
                "the target must be online when the request is created"
            ),
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise GateError(
            "remote_snapshot_unavailable",
            "ssh",
            f"target executable snapshot on {host!r} did not return JSON",
        ) from exc
    return _parse_snapshot_payload(host, unique_paths, payload)


def reverify_remote_command_snapshots(
    payload: Mapping[str, Any],
    selected_command_ids: Sequence[str],
    *,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any] | None:
    """Re-snapshot selected remote executables just before approval.

    Returns fresh host facts when verification ran, or ``None`` when skipped
    (local targets and legacy remote gates without a target snapshot marker).
    """
    target = payload.get("target")
    if not (isinstance(target, Mapping) and bool(target.get("remote"))):
        return None
    snapshot = target.get("snapshot")
    if not (isinstance(snapshot, Mapping) and snapshot.get("taken_on") == "target"):
        return None
    host = str(target.get("host") or "")
    request = payload.get("request")
    commands = request.get("commands") if isinstance(request, Mapping) else None
    if not isinstance(commands, list):
        raise GateError(
            "snapshot_mismatch",
            "payload.sudo.request.commands",
            "sudo command executable no longer matches the reviewed snapshot",
        )
    selected = set(selected_command_ids)
    reviewed: list[tuple[str, str, str]] = []
    for index, command in enumerate(commands):
        if not isinstance(command, Mapping):
            continue
        command_id = command.get("id")
        if command_id not in selected:
            continue
        argv = command.get("argv")
        expected = command.get("executable_sha256")
        if not isinstance(argv, list) or not argv or not isinstance(argv[0], str):
            raise GateError(
                "snapshot_mismatch",
                f"commands[{index}].argv[0]",
                "sudo command executable no longer matches the reviewed snapshot",
            )
        if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
            raise GateError(
                "snapshot_mismatch",
                f"commands[{index}].executable_sha256",
                "sudo command executable no longer matches the reviewed snapshot",
            )
        reviewed.append((str(command_id), argv[0], expected))
    fresh = snapshot_remote_executables(
        host,
        [path for _command_id, path, _expected in reviewed],
        command_runner=command_runner,
    )
    by_path = fresh.by_path()
    for command_id, path, expected in reviewed:
        result = by_path.get(path)
        target_label = f"commands[{command_id}].argv[0]"
        if result is None:
            raise GateError(
                "unsnapshotshotted_executable",
                target_label,
                "target did not snapshot this executable",
            )
        if result.error_code:
            raise GateError(
                result.error_code,
                target_label,
                result.message or "cannot snapshot executable",
            )
        if result.sha256 != expected:
            raise GateError(
                "snapshot_mismatch",
                f"commands[{command_id}].executable_sha256",
                "sudo command executable no longer matches the reviewed snapshot",
            )
    return dict(fresh.host_facts)


def _parse_snapshot_payload(
    host: str,
    paths: tuple[str, ...],
    payload: object,
) -> _RemoteExecutableSnapshot:
    if not isinstance(payload, Mapping):
        raise GateError(
            "remote_snapshot_unavailable",
            "ssh",
            f"target executable snapshot on {host!r} did not return an object",
        )
    if (
        payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION
        or payload.get("kind") != SNAPSHOT_KIND
    ):
        raise GateError(
            "remote_snapshot_unavailable",
            "ssh",
            f"upgrade sase on {host}",
        )
    facts = payload.get("host_facts")
    if not isinstance(facts, Mapping) or not isinstance(facts.get("platform"), str):
        raise GateError(
            "remote_snapshot_unavailable",
            "ssh",
            f"target executable snapshot on {host!r} is missing host facts",
        )
    raw_entries = payload.get("executables")
    if not isinstance(raw_entries, list):
        raise GateError(
            "remote_snapshot_unavailable",
            "ssh",
            f"target executable snapshot on {host!r} is missing executables",
        )
    executables = tuple(_parse_snapshot_entry(host, item) for item in raw_entries)
    by_path = {item.path: item for item in executables}
    missing = [path for path in paths if path not in by_path]
    if missing:
        raise GateError(
            "remote_snapshot_unavailable",
            "ssh",
            f"target executable snapshot on {host!r} omitted {missing[0]!r}",
        )
    return _RemoteExecutableSnapshot(
        host_facts={
            "full_disk_access": facts.get("full_disk_access"),
            "platform": str(facts["platform"]),
        },
        executables=executables,
    )


def _parse_snapshot_entry(host: str, value: object) -> ExecutableSnapshot:
    if not isinstance(value, Mapping) or not isinstance(value.get("path"), str):
        raise GateError(
            "remote_snapshot_unavailable",
            "ssh",
            f"target executable snapshot on {host!r} has an invalid entry",
        )
    path = str(value["path"])
    error_code = value.get("error_code")
    sha256 = value.get("sha256")
    message = value.get("message")
    if error_code is not None:
        if error_code not in _KNOWN_SNAPSHOT_ERRORS or not isinstance(error_code, str):
            raise GateError(
                "remote_snapshot_unavailable",
                "ssh",
                f"target executable snapshot on {host!r} has an invalid error",
            )
        return ExecutableSnapshot(
            path=path,
            error_code=error_code,
            message=str(message) if message is not None else None,
        )
    if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
        raise GateError(
            "remote_snapshot_unavailable",
            "ssh",
            f"target executable snapshot on {host!r} has an invalid hash",
        )
    return ExecutableSnapshot(path=path, sha256=sha256)


def _unique_paths(paths: Sequence[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for path in paths:
        if path not in seen:
            seen.append(path)
    return tuple(seen)


def _remote_snapshot_unavailable(host: str, exc: GateError) -> GateError:
    if exc.code in {"invalid_ssh_target"}:
        return exc
    if (
        exc.code
        in {
            "remote_sudo_contract_mismatch",
            "remote_sudo_unavailable",
        }
        and "upgrade" in str(exc).lower()
    ):
        return GateError(
            "remote_snapshot_unavailable", "ssh", f"upgrade sase on {host}"
        )
    if exc.code == "remote_sudo_contract_mismatch":
        return GateError(
            "remote_snapshot_unavailable", "ssh", f"upgrade sase on {host}"
        )
    return GateError(
        "remote_snapshot_unavailable",
        "ssh",
        (
            f"could not snapshot executables on {host!r}; "
            "the target must be online when the request is created"
        ),
    )


__all__ = [
    "reverify_remote_command_snapshots",
    "snapshot_remote_executables",
]
