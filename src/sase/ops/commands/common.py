"""Shared helpers for durable domain command runners."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sase.ops.cli import finish_operation
from sase.ops.errors import OperationIOError


def run_and_finish(
    *,
    operation: str,
    body: Callable[[], tuple[bool, str, Mapping[str, Any] | None]],
    args: Any = None,
) -> int:
    """Run *body* and emit its typed success or failure result."""
    try:
        success, message, payload = body()
    except OperationIOError as exc:
        return finish_operation(
            operation=operation,
            success=False,
            message=str(exc),
            error=str(exc),
            args=args,
        )
    except Exception as exc:
        return finish_operation(
            operation=operation,
            success=False,
            message=str(exc),
            error=str(exc),
            args=args,
        )
    return finish_operation(
        operation=operation,
        success=success,
        message=message,
        error=None if success else message,
        payload=payload,
        args=args,
    )


__all__ = ["run_and_finish"]
