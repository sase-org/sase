"""Shared helpers for durable domain command runners."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sase.ops.cli import finish_operation
from sase.ops.errors import OperationIOError


@dataclass(frozen=True)
class OperationCommandResult:
    """Result tuple for a command with a domain-specific exit code."""

    success: bool
    message: str
    payload: Mapping[str, Any] | None
    exit_code: int | None = None


def run_and_finish(
    *,
    operation: str,
    body: Callable[
        [],
        tuple[bool, str, Mapping[str, Any] | None] | OperationCommandResult,
    ],
    args: Any = None,
    print_message: bool = True,
) -> int:
    """Run *body* and emit its typed success or failure result."""
    try:
        result = body()
    except OperationIOError as exc:
        return finish_operation(
            operation=operation,
            success=False,
            message=str(exc),
            error=str(exc),
            args=args,
            print_message=print_message,
        )
    except Exception as exc:
        return finish_operation(
            operation=operation,
            success=False,
            message=str(exc),
            error=str(exc),
            args=args,
            print_message=print_message,
        )
    if isinstance(result, OperationCommandResult):
        success = result.success
        message = result.message
        payload = result.payload
        exit_code = result.exit_code
    else:
        success, message, payload = result
        exit_code = None
    emitted = finish_operation(
        operation=operation,
        success=success,
        message=message,
        error=None if success else message,
        payload=payload,
        args=args,
        print_message=print_message,
    )
    return emitted if exit_code is None else exit_code


__all__ = ["OperationCommandResult", "run_and_finish"]
