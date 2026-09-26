"""Pending-marker handoff from an agent runner to an agent-session turn."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
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


def will_handoff_turn_to_agent_runner(
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return whether a handoff helper will terminate the current runner."""
    current_env = env if env is not None else os.environ
    return bool(current_env.get("SASE_AGENT"))


def maybe_handoff_turn_from_agent(
    *,
    marker_name: str,
    marker_data: Mapping[str, Any],
    artifacts_dir: str | None = None,
    env: Mapping[str, str] | None = None,
    on_marker_written: Callable[[], None] | None = None,
    member: str = "turn",
) -> bool:
    """Write a pending marker and kill this runner when inside an agent."""
    current_env = env if env is not None else os.environ
    if not current_env.get("SASE_AGENT"):
        return False

    resolved_artifacts_dir = artifacts_dir or current_env.get("SASE_ARTIFACTS_DIR")
    if not resolved_artifacts_dir:
        raise TurnHandoffError(
            f"cannot hand {member} to agent runner: SASE_ARTIFACTS_DIR is unset",
            member=member,
        )

    write_turn_pending_marker(
        marker_name,
        marker_data,
        resolved_artifacts_dir,
        member=member,
    )
    if on_marker_written is not None:
        on_marker_written()

    from sase.main.utils import kill_agent_runner_group

    kill_agent_runner_group(resolved_artifacts_dir)
    return True


def write_turn_pending_marker(
    marker_name: str,
    marker_data: Mapping[str, Any],
    artifacts_dir: str,
    *,
    timestamp: float | None = None,
    member: str = "turn",
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
        )
    except (OSError, PendingHandoffError) as exc:
        raise TurnHandoffError(
            f"could not write {member} handoff marker: {exc}", member=member
        ) from exc

    # A pending marker supersedes any in-flight marker the handoff command
    # wrote before its slow work (sase-18e.3 aborted-handoff evidence).
    from sase.agent.handoff_inflight import clear_handoff_inflight_marker

    clear_handoff_inflight_marker(artifacts_dir)
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
    "maybe_handoff_turn_from_agent",
    "will_handoff_turn_to_agent_runner",
    "write_turn_pending_marker",
]
