"""Shared CLI helpers for durable operation request/result sidecars."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import OperationIOError
from .io import read_operation_request, write_operation_result
from .models import (
    OPERATION_ENV,
    PROC_ID_ENV,
    REQUEST_ENV,
    RESULT_ENV,
    DurableOperationRequest,
    DurableOperationResult,
)


def add_operation_io_flags(parser: argparse.ArgumentParser) -> None:
    """Add optional request/result path flags, sorted alphabetically."""
    parser.add_argument(
        "-Q",
        "--request-path",
        dest="operation_request_path",
        default=None,
        metavar="PATH",
        help=(
            "Private versioned operation request sidecar. Defaults to "
            f"${REQUEST_ENV} when that environment variable is set."
        ),
    )
    parser.add_argument(
        "-R",
        "--result-path",
        dest="operation_result_path",
        default=None,
        metavar="PATH",
        help=(
            "Private versioned typed result sidecar. Defaults to "
            f"${RESULT_ENV} when that environment variable is set."
        ),
    )


def resolve_request_path(args: argparse.Namespace | None = None) -> Path | None:
    """Return the request sidecar path from flags or the proc environment."""
    explicit = None if args is None else getattr(args, "operation_request_path", None)
    raw = explicit or os.environ.get(REQUEST_ENV)
    return None if not raw else Path(raw)


def resolve_result_path(args: argparse.Namespace | None = None) -> Path | None:
    """Return the result sidecar path from flags or the proc environment."""
    explicit = None if args is None else getattr(args, "operation_result_path", None)
    raw = explicit or os.environ.get(RESULT_ENV)
    return None if not raw else Path(raw)


def resolve_proc_id() -> str:
    """Return the durable proc id from the supervisor environment, or empty."""
    return os.environ.get(PROC_ID_ENV, "").strip()


def load_request(
    operation: str,
    args: argparse.Namespace | None = None,
    *,
    required: bool = False,
) -> DurableOperationRequest:
    """Load the versioned request sidecar, or return an empty payload."""
    path = resolve_request_path(args)
    if path is None:
        if required:
            raise OperationIOError(
                "missing",
                f"operation {operation} requires a request sidecar "
                f"(-Q/--request-path or ${REQUEST_ENV})",
            )
        return DurableOperationRequest(operation=operation, payload={})
    return read_operation_request(path, expected_operation=operation)


def emit_operation_result(
    *,
    operation: str,
    success: bool,
    message: str,
    error: str | None = None,
    payload: Mapping[str, Any] | None = None,
    result_path: str | Path | None = None,
    proc_id: str | None = None,
    args: argparse.Namespace | None = None,
) -> DurableOperationResult:
    """Write a typed result when a result path is configured."""
    dest = Path(result_path) if result_path is not None else resolve_result_path(args)
    resolved_proc_id = (proc_id or resolve_proc_id() or "direct").strip()
    result = DurableOperationResult(
        operation=os.environ.get(OPERATION_ENV, operation) or operation,
        proc_id=resolved_proc_id,
        success=success,
        message=message,
        error=error if not success else None,
        payload=None if payload is None else dict(payload),
    )
    if dest is not None:
        write_operation_result(dest, result)
    return result


def finish_operation(
    *,
    operation: str,
    success: bool,
    message: str,
    error: str | None = None,
    payload: Mapping[str, Any] | None = None,
    args: argparse.Namespace | None = None,
    print_message: bool = True,
) -> int:
    """Emit a typed result and return the process exit code."""
    result = emit_operation_result(
        operation=operation,
        success=success,
        message=message,
        error=error,
        payload=payload,
        args=args,
    )
    if print_message and result.message:
        stream = sys.stdout if success else sys.stderr
        print(result.message, file=stream)
    return 0 if success else 1


__all__ = [
    "add_operation_io_flags",
    "emit_operation_result",
    "finish_operation",
    "load_request",
    "resolve_proc_id",
    "resolve_request_path",
    "resolve_result_path",
]
