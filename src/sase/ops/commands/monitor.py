"""Noninteractive monitor-stop runner used by durable procs."""

from __future__ import annotations

from collections.abc import Mapping

from sase.ops.cli import emit_operation_result
from sase.ops.names import MONITOR_STOP


def emit_monitor_stop_result(
    *,
    success: bool,
    message: str,
    payload: Mapping[str, object] | None = None,
) -> None:
    """Write a typed monitor-stop result when a result path is configured."""
    emit_operation_result(
        operation=MONITOR_STOP,
        success=success,
        message=message,
        error=None if success else message,
        payload=payload,
    )


__all__ = ["emit_monitor_stop_result"]
