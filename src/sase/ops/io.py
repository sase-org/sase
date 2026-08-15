"""Atomic mode-0600 read/write helpers for durable operation sidecars."""

from __future__ import annotations

import json
import os
import stat
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import OperationIOError
from .models import (
    OPERATION_SCHEMA_VERSION,
    SUPPORTED_OPERATION_SCHEMA_VERSIONS,
    DurableOperationRequest,
    DurableOperationResult,
)

_PRIVATE_MODE = 0o600


def write_private_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Atomically write *payload* as a regular file with mode ``0600``."""
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(dict(payload), indent=2, sort_keys=True).encode("utf-8")
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.{time.time_ns()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, _PRIVATE_MODE)
    try:
        os.write(fd, encoded)
        os.fsync(fd)
    except OSError:
        os.close(fd)
        _unlink_quietly(tmp)
        raise
    else:
        os.close(fd)
    try:
        os.replace(tmp, dest)
        os.chmod(dest, _PRIVATE_MODE)
    except OSError:
        _unlink_quietly(tmp)
        raise


def write_operation_request(path: str | Path, request: DurableOperationRequest) -> None:
    """Publish a versioned operation request sidecar."""
    write_private_json(path, request.to_dict())


def write_operation_result(path: str | Path, result: DurableOperationResult) -> None:
    """Publish a versioned typed operation result sidecar."""
    write_private_json(path, result.to_dict())


def read_operation_request(
    path: str | Path,
    *,
    expected_operation: str | None = None,
) -> DurableOperationRequest:
    """Load and validate a durable operation request sidecar."""
    payload = _read_sidecar_object(path)
    operation = _required_str(payload, "operation", path)
    if expected_operation is not None and operation != expected_operation:
        raise OperationIOError(
            "mismatched",
            f"operation sidecar {path} has operation {operation!r}, "
            f"expected {expected_operation!r}",
        )
    raw_payload = payload.get("payload")
    if raw_payload is None:
        domain: dict[str, Any] = {}
    elif isinstance(raw_payload, dict):
        domain = dict(raw_payload)
    else:
        raise OperationIOError(
            "malformed",
            f"operation request {path} payload must be a JSON object",
        )
    return DurableOperationRequest(
        operation=operation,
        payload=domain,
        schema_version=_schema_version(payload, path),
    )


def read_operation_result(
    path: str | Path,
    *,
    expected_operation: str | None = None,
    expected_proc_id: str | None = None,
) -> DurableOperationResult:
    """Load and validate a durable operation result sidecar."""
    payload = _read_sidecar_object(path)
    operation = _required_str(payload, "operation", path)
    proc_id = _required_str(payload, "proc_id", path)
    if expected_operation is not None and operation != expected_operation:
        raise OperationIOError(
            "mismatched",
            f"operation result {path} has operation {operation!r}, "
            f"expected {expected_operation!r}",
        )
    if expected_proc_id is not None and proc_id != expected_proc_id:
        raise OperationIOError(
            "mismatched",
            f"operation result {path} has proc_id {proc_id!r}, "
            f"expected {expected_proc_id!r}",
        )
    success = payload.get("success")
    if not isinstance(success, bool):
        raise OperationIOError(
            "malformed",
            f"operation result {path} success must be a boolean",
        )
    message = payload.get("message")
    if not isinstance(message, str):
        raise OperationIOError(
            "malformed",
            f"operation result {path} message must be a string",
        )
    error = payload.get("error")
    if error is not None and not isinstance(error, str):
        raise OperationIOError(
            "malformed",
            f"operation result {path} error must be a string or null",
        )
    typed = payload.get("payload")
    if typed is not None and not isinstance(typed, dict):
        raise OperationIOError(
            "malformed",
            f"operation result {path} payload must be a JSON object or null",
        )
    return DurableOperationResult(
        operation=operation,
        proc_id=proc_id,
        success=success,
        message=message,
        error=error,
        payload=None if typed is None else dict(typed),
        schema_version=_schema_version(payload, path),
    )


def _read_sidecar_object(path: str | Path) -> dict[str, Any]:
    dest = Path(path)
    if not dest.exists():
        raise OperationIOError("missing", f"operation sidecar is missing: {dest}")
    try:
        info = dest.lstat()
    except OSError as exc:
        raise OperationIOError(
            "missing", f"could not stat operation sidecar {dest}: {exc}"
        ) from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise OperationIOError(
            "not_regular",
            f"operation sidecar {dest} is not a regular file",
        )
    if info.st_uid != os.getuid():
        raise OperationIOError(
            "permission",
            f"operation sidecar {dest} is not owned by the current user",
        )
    if stat.S_IMODE(info.st_mode) != _PRIVATE_MODE:
        raise OperationIOError(
            "permission",
            f"operation sidecar {dest} must have mode 0600",
        )
    try:
        raw = dest.read_text(encoding="utf-8")
    except OSError as exc:
        raise OperationIOError(
            "malformed", f"could not read operation sidecar {dest}: {exc}"
        ) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OperationIOError(
            "malformed",
            f"operation sidecar {dest} is not valid JSON: {exc.msg}",
        ) from exc
    if not isinstance(payload, dict):
        raise OperationIOError(
            "malformed",
            f"operation sidecar {dest} must contain a JSON object",
        )
    return payload


def _schema_version(payload: Mapping[str, Any], path: str | Path) -> int:
    version = payload.get("schema_version", OPERATION_SCHEMA_VERSION)
    if not isinstance(version, int) or isinstance(version, bool):
        raise OperationIOError(
            "malformed",
            f"operation sidecar {path} schema_version must be an integer",
        )
    if version not in SUPPORTED_OPERATION_SCHEMA_VERSIONS:
        raise OperationIOError(
            "unsupported_schema",
            f"operation sidecar {path} schema_version {version} is not supported",
        )
    return version


def _required_str(payload: Mapping[str, Any], key: str, path: str | Path) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise OperationIOError(
            "malformed",
            f"operation sidecar {path} field {key!r} must be a non-empty string",
        )
    return value


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


__all__ = [
    "read_operation_request",
    "read_operation_result",
    "write_operation_request",
    "write_operation_result",
    "write_private_json",
]
