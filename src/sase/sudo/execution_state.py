"""Versioned detached sudo execution records and their persistence."""

from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.notification_gates.durability import (
    atomic_write_json,
    file_lock,
    fsync_dir,
    read_json_object,
)
from sase.notification_gates.models import GateError

EXECUTION_STATE_FILENAME = "execution-state.json"
EXECUTION_STATE_SCHEMA_VERSION = 1
HANDOFF_DIR_MODE = 0o700
HANDOFF_FILE_MODE = 0o600
LEDGER_FILENAME = "ledger.json"
LOG_FILENAME = "output.log"
MANIFEST_FILENAME = "manifest.json"
RESPONSE_LOCK_FILENAME = ".response.lock"
STOP_FILENAME = "stop"
SUDO_EXEC_STARTED_KIND = "sudo_exec_started"


@dataclass(frozen=True)
class SudoExecutionState:
    """Versioned in-flight detached sudo execution record."""

    gate_id: str
    selected_command_ids: tuple[str, ...]
    manifest_sha256: str
    handoff_dir: str
    handshake: dict[str, Any] | None = None
    finalize_proc_id: str | None = None
    target_kind: str = "local"
    target_host: str | None = None
    startup_state: str = "legacy"
    operation_payload_digest: str | None = None
    authorization_id: str | None = None
    remote_handoff: dict[str, str] | None = None
    schema_version: int = EXECUTION_STATE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "authorization_id": self.authorization_id,
            "finalize_proc_id": self.finalize_proc_id,
            "gate_id": self.gate_id,
            "handoff_dir": self.handoff_dir,
            "handshake": None if self.handshake is None else dict(self.handshake),
            "manifest_sha256": self.manifest_sha256,
            "operation_payload_digest": self.operation_payload_digest,
            "schema_version": self.schema_version,
            "selected_command_ids": list(self.selected_command_ids),
            "startup_state": self.startup_state,
            "target_host": self.target_host,
            "target_kind": self.target_kind,
        }
        if self.remote_handoff is not None:
            payload["remote_handoff"] = dict(self.remote_handoff)
        return payload


def _execution_state_path(bundle_root: Path) -> Path:
    """Return the execution-state path co-located with a sudo gate bundle."""
    return Path(bundle_root) / EXECUTION_STATE_FILENAME


def execution_lock(bundle_root: Path) -> AbstractContextManager[None]:
    """Serialize in-flight execution-record transitions on the gate bundle."""
    return file_lock(Path(bundle_root) / RESPONSE_LOCK_FILENAME)


def load_execution_state(bundle_root: Path) -> SudoExecutionState | None:
    """Return the execution record, or ``None`` when it is absent."""
    path = _execution_state_path(bundle_root)
    if not path.exists():
        return None
    try:
        payload = read_json_object(path)
    except GateError:
        raise GateError(
            "invalid_sudo_execution_state",
            str(path),
            "sudo execution-state JSON is invalid",
        ) from None
    return _state_from_payload(payload, path=path)


def write_execution_state(bundle_root: Path, state: SudoExecutionState) -> None:
    """Atomically write a permission-safe execution record."""
    path = _execution_state_path(bundle_root)
    atomic_write_json(path, state.to_dict())
    os.chmod(path, HANDOFF_FILE_MODE)


def clear_execution_state(bundle_root: Path) -> None:
    """Remove the execution record when present."""
    path = _execution_state_path(bundle_root)
    try:
        path.unlink()
    except FileNotFoundError:
        return
    fsync_dir(path.parent)


def _state_from_payload(
    payload: Mapping[str, Any], *, path: Path
) -> SudoExecutionState:
    version = payload.get("schema_version")
    if version != EXECUTION_STATE_SCHEMA_VERSION:
        raise GateError(
            "invalid_sudo_execution_state",
            str(path),
            "unsupported sudo execution-state schema",
        )
    gate_id = payload.get("gate_id")
    handoff_dir = payload.get("handoff_dir")
    digest = payload.get("manifest_sha256")
    selected = payload.get("selected_command_ids")
    if not isinstance(gate_id, str) or not gate_id:
        raise GateError(
            "invalid_sudo_execution_state",
            "gate_id",
            "sudo execution record is missing gate_id",
        )
    if not isinstance(handoff_dir, str) or not handoff_dir:
        raise GateError(
            "invalid_sudo_execution_state",
            "handoff_dir",
            "sudo execution record is missing handoff_dir",
        )
    if not isinstance(digest, str) or not digest:
        raise GateError(
            "invalid_sudo_execution_state",
            "manifest_sha256",
            "sudo execution record is missing manifest_sha256",
        )
    if not isinstance(selected, list) or any(
        not isinstance(item, str) for item in selected
    ):
        raise GateError(
            "invalid_sudo_execution_state",
            "selected_command_ids",
            "sudo execution record command ids must be strings",
        )
    handshake = payload.get("handshake")
    if handshake is not None and not isinstance(handshake, dict):
        raise GateError(
            "invalid_sudo_execution_state",
            "handshake",
            "sudo execution record handshake must be an object",
        )
    proc_id = payload.get("finalize_proc_id")
    if proc_id is not None and not isinstance(proc_id, str):
        raise GateError(
            "invalid_sudo_execution_state",
            "finalize_proc_id",
            "sudo execution record finalize_proc_id must be a string",
        )
    target_kind = payload.get("target_kind")
    startup_state = payload.get("startup_state")
    target_host = payload.get("target_host")
    operation_payload_digest = payload.get("operation_payload_digest")
    authorization_id = payload.get("authorization_id")
    if target_kind is None:
        target_kind = "unknown"
    if startup_state is None:
        startup_state = "unknown"
    if target_kind not in {"local", "remote", "unknown"}:
        raise GateError(
            "invalid_sudo_execution_state",
            "target_kind",
            "sudo execution record target_kind is invalid",
        )
    if startup_state not in {
        "legacy",
        "reserved",
        "authenticating",
        "starting",
        "started",
        "settling",
        "settled",
        "terminal",
        "unknown",
    }:
        raise GateError(
            "invalid_sudo_execution_state",
            "startup_state",
            "sudo execution record startup_state is invalid",
        )
    if target_host is not None and not isinstance(target_host, str):
        raise GateError(
            "invalid_sudo_execution_state",
            "target_host",
            "sudo execution record target_host must be a string",
        )
    if operation_payload_digest is not None and not isinstance(
        operation_payload_digest, str
    ):
        raise GateError(
            "invalid_sudo_execution_state",
            "operation_payload_digest",
            "sudo execution record operation_payload_digest must be a string",
        )
    if authorization_id is not None and not isinstance(authorization_id, str):
        raise GateError(
            "invalid_sudo_execution_state",
            "authorization_id",
            "sudo execution record authorization_id must be a string",
        )
    remote_handoff = _remote_handoff_from_payload(
        payload.get("remote_handoff"),
        target_kind=str(target_kind),
        target_host=target_host if isinstance(target_host, str) else None,
    )
    return SudoExecutionState(
        schema_version=EXECUTION_STATE_SCHEMA_VERSION,
        gate_id=gate_id,
        selected_command_ids=tuple(selected),
        manifest_sha256=digest,
        handoff_dir=handoff_dir,
        handshake=None if handshake is None else dict(handshake),
        finalize_proc_id=proc_id,
        target_kind=target_kind,
        target_host=target_host,
        startup_state=startup_state,
        operation_payload_digest=operation_payload_digest,
        authorization_id=authorization_id,
        remote_handoff=remote_handoff,
    )


_REMOTE_HANDOFF_KEYS = (
    "directory",
    "handshake",
    "ledger",
    "log",
    "manifest",
    "stop",
)


def _remote_handoff_from_payload(
    value: Any,
    *,
    target_kind: str,
    target_host: str | None,
) -> dict[str, str] | None:
    """Return validated remote path metadata, or ``None`` for legacy records."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise GateError(
            "invalid_sudo_execution_state",
            "remote_handoff",
            "sudo execution record remote_handoff must be an object",
        )
    if target_kind != "remote":
        raise GateError(
            "invalid_sudo_execution_state",
            "remote_handoff",
            "sudo remote handoff metadata requires target_kind remote",
        )
    if not target_host:
        raise GateError(
            "invalid_sudo_execution_state",
            "target_host",
            "sudo remote handoff metadata requires target_host",
        )
    paths: dict[str, str] = {}
    for key in _REMOTE_HANDOFF_KEYS:
        item = value.get(key)
        if not isinstance(item, str) or not item or item.endswith("/"):
            raise GateError(
                "invalid_sudo_execution_state",
                f"remote_handoff.{key}",
                "sudo remote handoff path must be a non-empty absolute path",
            )
        if not item.startswith("/") or "\x00" in item:
            raise GateError(
                "invalid_sudo_execution_state",
                f"remote_handoff.{key}",
                "sudo remote handoff path must be a safe absolute path",
            )
        parts = Path(item).parts
        if any(part in {".", ".."} for part in parts):
            raise GateError(
                "invalid_sudo_execution_state",
                f"remote_handoff.{key}",
                "sudo remote handoff path must not contain relative components",
            )
        paths[key] = item
    directory = paths["directory"]
    prefix = directory.rstrip("/") + "/"
    seen = {directory}
    for key in _REMOTE_HANDOFF_KEYS:
        if key == "directory":
            continue
        item = paths[key]
        if not item.startswith(prefix) or item == prefix:
            raise GateError(
                "invalid_sudo_execution_state",
                f"remote_handoff.{key}",
                "sudo remote handoff path must be inside the remote directory",
            )
        if item in seen:
            raise GateError(
                "invalid_sudo_execution_state",
                f"remote_handoff.{key}",
                "sudo remote handoff paths must be unique",
            )
        seen.add(item)
    return paths


__all__ = [
    "EXECUTION_STATE_FILENAME",
    "EXECUTION_STATE_SCHEMA_VERSION",
    "HANDOFF_DIR_MODE",
    "HANDOFF_FILE_MODE",
    "LEDGER_FILENAME",
    "LOG_FILENAME",
    "MANIFEST_FILENAME",
    "RESPONSE_LOCK_FILENAME",
    "STOP_FILENAME",
    "SUDO_EXEC_STARTED_KIND",
    "SudoExecutionState",
    "clear_execution_state",
    "execution_lock",
    "load_execution_state",
    "write_execution_state",
]
