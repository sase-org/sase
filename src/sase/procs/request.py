"""Typed submission request for the unified proc service."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from .models import COMMAND_PROC_KIND, STORE_LOG_OWNER


@dataclass(frozen=True)
class ProcSubmitRequest:
    """One durable proc submission used by CLI, API, and later facades.

    Execution state is reserved on the proc row. Optional settlement policy
    (workspace claim, artifacts, follow-up, result envelope path) is persisted
    beside the row so a restarted supervisor can resume it exactly once.
    """

    argv: Sequence[str]
    label: str
    cwd: str | Path
    origin: str
    command: Sequence[str] | None = None
    proc_id: str | None = None
    kind: str = COMMAND_PROC_KIND
    session_id: str | None = None
    session_label: str | None = None
    project: str | None = None
    workspace_num: int | None = None
    tags: Sequence[str] = ()
    cl_name: str | None = None
    env: Mapping[str, str] | None = None
    shell_name: str | None = None
    shell_kind: str | None = "proc"
    concurrency_keys: Sequence[str] = ()
    request_fingerprint: str | None = None
    reserved_by: str | None = None
    timeout_seconds: int | None = None
    idle_timeout_seconds: int | None = None
    log_path: str | Path | None = None
    log_owner: str = STORE_LOG_OWNER
    artifacts_dir: str | Path | None = None
    request_path: str | Path | None = None
    result_path: str | Path | None = None
    operation: str | None = None
    operation_payload: Mapping[str, Any] | None = None
    workspace_claim: Mapping[str, Any] | None = None
    followup: Mapping[str, Any] | None = None


def proc_request_fingerprint(
    request: ProcSubmitRequest,
    *,
    proc_id: str,
    cwd: str,
    argv: Sequence[str],
) -> str:
    """Return a stable fingerprint, unique per unnamed submit unless provided.

    When *request* carries a logical ``command``, that value is fingerprinted
    instead of the execution ``argv`` so bootstrap wrappers do not fork a
    new identity for the same work.
    """
    if request.request_fingerprint:
        return request.request_fingerprint
    payload = {
        "argv": _logical_argv(request, argv),
        "concurrency_keys": sorted(set(request.concurrency_keys)),
        "cwd": cwd,
        "idle_timeout_seconds": request.idle_timeout_seconds,
        "kind": request.kind,
        "label": request.label,
        "origin": request.origin,
        "proc_id": proc_id,
        "project": request.project,
        "session_id": request.session_id,
        "shell_name": request.shell_name,
        "timeout_seconds": request.timeout_seconds,
        "workspace_num": request.workspace_num,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def request_sidecar_payload(
    request: ProcSubmitRequest,
    *,
    proc_id: str,
    argv: Sequence[str],
    cwd: str,
    log_path: str,
    fingerprint: str,
) -> dict[str, Any]:
    """Return the durable request sidecar written before supervisor spawn."""
    return {
        "artifacts_dir": (
            str(request.artifacts_dir) if request.artifacts_dir is not None else None
        ),
        "argv": list(argv),
        "command": _logical_argv(request, argv),
        "cwd": cwd,
        "env": dict(request.env) if request.env is not None else None,
        "followup": dict(request.followup) if request.followup is not None else None,
        "log_path": log_path,
        "operation": request.operation,
        "proc_id": proc_id,
        "request_fingerprint": fingerprint,
        "request_path": (
            str(request.request_path) if request.request_path is not None else None
        ),
        "result_path": (
            str(request.result_path) if request.result_path is not None else None
        ),
        "workspace_claim": (
            dict(request.workspace_claim)
            if request.workspace_claim is not None
            else None
        ),
    }


def _logical_argv(request: ProcSubmitRequest, argv: Sequence[str]) -> list[str]:
    if request.command is None:
        return list(argv)
    return [str(part) for part in request.command]


__all__ = [
    "ProcSubmitRequest",
    "proc_request_fingerprint",
    "request_sidecar_payload",
]
