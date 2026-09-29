"""Shared run-lookup helpers for the ``sase tool`` lifecycle controls.

This is a private module: the names defined here are public only so the
``sase.tool.control_*`` siblings can import them without touching a
``_``-prefixed name across modules. External code must keep importing
the ``sase.tool.control`` facade.
"""

from __future__ import annotations

from typing import Any

from sase.core.tool_run import tool_run_show


TERMINAL_RUN_STATES = frozenset(
    {"succeeded", "failed", "signaled", "interrupted", "lost"}
)
UNSETTLED_RUN_STATES = frozenset({"created", "running"})


class UnknownRunError(ValueError):
    """The requested run id is not in the ledger (exit 2)."""


def load_run(run_id: str) -> dict[str, Any]:
    """Return the stored run dict, or raise :class:`UnknownRunError`."""

    envelope = tool_run_show(run_id)
    run = envelope.get("run")
    if not isinstance(run, dict) or str(run.get("run_id") or "") != run_id:
        diagnostic = "; ".join(str(item) for item in envelope.get("diagnostics") or ())
        raise UnknownRunError(diagnostic or f"tool run {run_id} was not found")
    return run


def is_settled(run: dict[str, Any]) -> bool:
    return str(run.get("state") or "") not in UNSETTLED_RUN_STATES


__all__ = [
    "UnknownRunError",
    "is_settled",
    "load_run",
    "TERMINAL_RUN_STATES",
    "UNSETTLED_RUN_STATES",
]
