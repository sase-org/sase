"""Noninteractive artifact-operation runners used by durable procs."""

from __future__ import annotations

from collections.abc import Mapping

from sase.ops.cli import emit_operation_result
from sase.ops.names import ARTIFACT_PRUNE_RUNS


def emit_artifact_prune_runs_result(
    *,
    success: bool,
    message: str,
    payload: Mapping[str, object] | None = None,
) -> None:
    """Write a typed prune-runs result when a result path is configured."""
    emit_operation_result(
        operation=ARTIFACT_PRUNE_RUNS,
        success=success,
        message=message,
        error=None if success else message,
        payload=payload,
    )


__all__ = ["emit_artifact_prune_runs_result"]
