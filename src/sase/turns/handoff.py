"""Pending-marker writer kept for archived kill-path readers.

In-agent handoff commands now stage and return. This module still writes the
historical pending-marker shape so archived runs, collision detection, and
runtime tests can interpret old handoffs.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.pending_handoff_write import (
    PendingHandoffError,
    write_pending_handoff_marker,
)


class TurnHandoffError(RuntimeError):
    """A pending turn handoff marker could not be written."""

    def __init__(self, message: str, *, member: str = "turn") -> None:
        super().__init__(message)
        self.member = member


def write_turn_pending_marker(
    marker_name: str,
    marker_data: Mapping[str, Any],
    artifacts_dir: str,
    *,
    timestamp: float | None = None,
    member: str = "turn",
    reservation_id: str | None = None,
) -> Path:
    """Persist a pending turn handoff marker for the runner to adopt."""
    payload = dict(marker_data)
    if timestamp is not None:
        payload["timestamp"] = timestamp
    try:
        marker_path = write_pending_handoff_marker(
            marker_name,
            payload,
            artifacts_dir=artifacts_dir,
            reservation_id=reservation_id,
        )
    except (OSError, PendingHandoffError) as exc:
        raise TurnHandoffError(
            f"could not write {member} handoff marker: {exc}", member=member
        ) from exc

    _touch_turn_refresh_pulse_for_artifacts_dir(artifacts_dir)
    return marker_path


def _touch_turn_refresh_pulse_for_artifacts_dir(artifacts_dir: str) -> None:
    """Nudge artifact watchers after a pending handoff marker mutation."""
    try:
        from sase.turns.settlement import (
            project_name_from_artifacts_dir,
            touch_turn_refresh_pulse,
        )

        touch_turn_refresh_pulse(project_name_from_artifacts_dir(artifacts_dir))
    except Exception:  # noqa: BLE001 - a refresh pulse must never fail the handoff.
        pass


__all__ = [
    "TurnHandoffError",
    "write_turn_pending_marker",
]
