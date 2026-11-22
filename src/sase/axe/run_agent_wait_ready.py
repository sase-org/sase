"""Stdlib-only ``ready.json`` reader shared by the runner and the lean waiter.

The full runner and the lean waiter (``run_agent_lean_wait.py``) must read the
very same rendezvous marker the very same way, but the lean waiter exists to
park near 15 MB, so this leaf imports nothing outside the standard library.
Do not add a ``sase.*`` import here: ``run_agent_wait_deps`` re-exports these
names for the heavier callers, never the other way around.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any


@dataclass(frozen=True)
class ReadyResult:
    """Runner-side ``ready.json`` read outcome plus telemetry.

    Truthy exactly when the marker releases the wait. ``released_by`` and
    ``dependencies_satisfied_at`` come straight from the marker payload;
    ``unwait`` marks a manual (TUI run-now) release.
    """

    resolved: bool = False
    released_by: str | None = None
    unwait: bool = False
    dependencies_satisfied_at: float | None = None

    def __bool__(self) -> bool:
        return self.resolved


def _read_json_dict(path: str) -> dict[str, Any] | None:
    """Load a JSON object from *path*, or None when absent or malformed."""
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _ready_float(value: object) -> float | None:
    """Return a numeric epoch from a marker payload value, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def read_ready_result(ready_path: str) -> ReadyResult:
    """Return whether a ready marker resolves the wait.

    A torn or otherwise unreadable marker is treated as not ready; the
    runner retries on its next poll (and the periodic fallback, which
    never reads ``ready.json``, still bounds the wait). Cancellation
    markers written by older SASE versions are stale state. Remove them
    and keep waiting for an actual successful resolution marker.
    """
    waiting_data = _read_json_dict(
        os.path.join(os.path.dirname(ready_path), "waiting.json")
    )
    if waiting_data is not None and waiting_data.get("cancelled_by_hijack") is True:
        return ReadyResult(False)
    try:
        with open(ready_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return ReadyResult(False)
    if not isinstance(data, dict):
        return ReadyResult(False)
    if not data.get("cancelled"):
        released_by = data.get("released_by")
        return ReadyResult(
            True,
            released_by if isinstance(released_by, str) else None,
            bool(data.get("unwait", False)),
            _ready_float(data.get("dependencies_satisfied_at")),
        )
    try:
        os.unlink(ready_path)
    except OSError:
        pass
    return ReadyResult(False)


__all__ = ["ReadyResult", "read_ready_result"]
