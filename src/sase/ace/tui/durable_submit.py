"""Additive ACE adapter for argv-only durable proc submissions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.ops import (
    DurableOperationRequest,
    DurableSubmitError,
)
from sase.procs import ProcSubmitRequest, submit_proc_request


@dataclass(frozen=True)
class DurableSubmitHandle:
    """Presentation handle for one supervisor-owned durable submission."""

    proc_id: str
    operation: str
    result_path: str


def reject_callable_submission(argv: object, request: object) -> None:
    """Reject callable argv or request values at the durable API boundary."""
    if callable(argv):
        raise DurableSubmitError("durable argv must not be a callable")
    if not isinstance(argv, Sequence) or isinstance(argv, (str, bytes)):
        raise DurableSubmitError("durable argv must be a non-empty sequence of strings")
    if not argv:
        raise DurableSubmitError("durable argv must be a non-empty sequence of strings")
    for index, part in enumerate(argv):
        if callable(part):
            raise DurableSubmitError(f"durable argv[{index}] must not be a callable")
        if not isinstance(part, str) or not part:
            raise DurableSubmitError("durable argv must contain only non-empty strings")
    if callable(request):
        raise DurableSubmitError("durable request must not be a callable")


def coerce_operation_request(
    operation: str, request: DurableOperationRequest | Mapping[str, Any]
) -> DurableOperationRequest:
    """Normalize a mapping or typed request and reject callables."""
    reject_callable_submission(["sase"], request)
    if isinstance(request, DurableOperationRequest):
        if request.operation != operation:
            raise DurableSubmitError(
                f"request operation {request.operation!r} does not match {operation!r}"
            )
        return request
    payload = request.get("payload", request)
    if callable(payload):
        raise DurableSubmitError("durable request payload must not be a callable")
    if not isinstance(payload, Mapping):
        raise DurableSubmitError("durable request payload must be a JSON object")
    return DurableOperationRequest(operation=operation, payload=dict(payload))


def submit_durable_proc_request(
    *,
    argv: Sequence[str],
    operation: str,
    request: DurableOperationRequest,
    cwd: str | Path,
    label: str,
    result_path: str | Path | None = None,
    request_fingerprint: str | None = None,
    concurrency_keys: Sequence[str] = (),
    origin: str = "ace",
    project: str | None = None,
    cl_name: str | None = None,
    session_id: str | None = None,
    workspace_claim: Mapping[str, Any] | None = None,
) -> DurableSubmitHandle:
    """Submit argv through the durable proc service. Never executes a callable."""
    reject_callable_submission(argv, request)
    submit_request = ProcSubmitRequest(
        argv=list(argv),
        label=label,
        cwd=cwd,
        origin=origin,
        operation=operation,
        operation_payload=dict(request.payload),
        result_path=result_path,
        request_fingerprint=request_fingerprint,
        concurrency_keys=list(concurrency_keys),
        project=project,
        cl_name=cl_name,
        session_id=session_id,
        workspace_claim=workspace_claim,
    )
    proc = submit_proc_request(submit_request)
    from sase.procs.runtime import proc_operation_result_path

    resolved_result = str(result_path or proc_operation_result_path(proc.proc_id))
    return DurableSubmitHandle(
        proc_id=proc.proc_id,
        operation=operation,
        result_path=resolved_result,
    )


__all__ = [
    "DurableSubmitHandle",
    "coerce_operation_request",
    "reject_callable_submission",
    "submit_durable_proc_request",
]
