"""Noninteractive tool-stop runner used by durable procs."""

from __future__ import annotations

from collections.abc import Mapping

from sase.ops.cli import emit_operation_result
from sase.ops.names import TOOL_STOP


def emit_tool_stop_result(
    *,
    success: bool,
    message: str,
    payload: Mapping[str, object] | None = None,
) -> None:
    """Write a typed tool-stop result when a result path is configured."""
    emit_operation_result(
        operation=TOOL_STOP,
        success=success,
        message=message,
        error=None if success else message,
        payload=payload,
    )


__all__ = ["emit_tool_stop_result"]
