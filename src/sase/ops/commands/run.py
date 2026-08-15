"""Typed result emission for ``sase run`` launches."""

from __future__ import annotations

from collections.abc import Mapping

from sase.ops.cli import emit_operation_result
from sase.ops.names import RUN_LAUNCH


def emit_run_launch_result(
    *,
    success: bool,
    message: str,
    payload: Mapping[str, object] | None = None,
) -> None:
    """Write a typed run-launch result when a result path is configured."""
    emit_operation_result(
        operation=RUN_LAUNCH,
        success=success,
        message=message,
        error=None if success else message,
        payload=payload,
    )


__all__ = ["emit_run_launch_result"]
