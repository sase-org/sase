"""Shared helpers for the staged-monitor split.

Public helpers needed by more than one ``start_stage_*`` module live here
with public names. This module is already private (``_``-prefixed), so
importing these names across the split is allowed while ``_private`` symbol
imports across the split stay forbidden.
"""

from __future__ import annotations

import shlex
from typing import Any

from .request import StartMonitorRequest


def claim_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the workspace claim context block from a launch payload."""
    workspace = payload.get("workspace")
    if not isinstance(workspace, dict):
        return {}
    raw = workspace.get("claim_context")
    return dict(raw) if isinstance(raw, dict) else {}


def command_argv(request: StartMonitorRequest) -> tuple[list[str], list[str]]:
    """Split a request command into display and execution argv forms."""
    command_parts = shlex.split(request.command) or [request.command]
    if request.execution_argv is not None:
        execution_parts = [str(part) for part in request.execution_argv if str(part)]
    else:
        execution_parts = list(command_parts)
    if not execution_parts:
        execution_parts = list(command_parts)
    return command_parts, execution_parts


def prepared_intent_ref(payload: dict[str, Any]) -> str | None:
    """Return the prepared-intent reference carried by a launch payload."""
    raw = payload.get("prepared_intent_ref") if isinstance(payload, dict) else None
    if isinstance(raw, str) and raw.strip():
        return raw
    resources = payload.get("resources") if isinstance(payload, dict) else None
    if isinstance(resources, dict):
        nested = resources.get("prepared_intent_ref")
        if isinstance(nested, str) and nested.strip():
            return nested
    return None


def optional_str(value: object) -> str | None:
    """Return stripped text or ``None`` for empty/missing values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "claim_context",
    "command_argv",
    "optional_str",
    "prepared_intent_ref",
]
