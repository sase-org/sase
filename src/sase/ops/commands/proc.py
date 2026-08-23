"""Noninteractive proc-operation runners used by durable procs."""

from __future__ import annotations

from collections.abc import Mapping

from sase.ops.cli import emit_operation_result
from sase.ops.names import PROC_KILL


def emit_proc_kill_result(
    *,
    success: bool,
    message: str,
    payload: Mapping[str, object] | None = None,
) -> None:
    """Write a typed proc-kill result when a result path is configured."""
    emit_operation_result(
        operation=PROC_KILL,
        success=success,
        message=message,
        error=None if success else message,
        payload=payload,
    )


__all__ = ["emit_proc_kill_result"]
