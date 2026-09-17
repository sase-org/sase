"""Pending-marker handoff from an agent runner to a family shell."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.agent.pending_handoff_write import (
    PendingHandoffError,
    write_pending_handoff_marker,
)


class ShellHandoffError(RuntimeError):
    """A pending shell handoff marker could not be written."""


def will_handoff_shell_to_agent_runner(
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return whether a handoff helper will terminate the current runner."""
    current_env = env if env is not None else os.environ
    return bool(current_env.get("SASE_AGENT"))


def maybe_handoff_shell_from_agent(
    *,
    marker_name: str,
    marker_data: Mapping[str, Any],
    artifacts_dir: str | None = None,
    env: Mapping[str, str] | None = None,
    on_marker_written: Callable[[], None] | None = None,
) -> bool:
    """Write a pending marker and kill this runner when inside an agent."""
    current_env = env if env is not None else os.environ
    if not current_env.get("SASE_AGENT"):
        return False

    resolved_artifacts_dir = artifacts_dir or current_env.get("SASE_ARTIFACTS_DIR")
    if not resolved_artifacts_dir:
        raise ShellHandoffError(
            "cannot hand shell to agent runner: SASE_ARTIFACTS_DIR is unset"
        )

    write_shell_pending_marker(
        marker_name,
        marker_data,
        resolved_artifacts_dir,
    )
    if on_marker_written is not None:
        on_marker_written()

    from sase.main.utils import kill_agent_runner_group

    kill_agent_runner_group(resolved_artifacts_dir)
    return True


def write_shell_pending_marker(
    marker_name: str,
    marker_data: Mapping[str, Any],
    artifacts_dir: str,
    *,
    timestamp: float | None = None,
) -> Path:
    """Persist a pending shell handoff marker for the runner to adopt."""
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
        raise ShellHandoffError(f"could not write shell handoff marker: {exc}") from exc

    _touch_shell_refresh_pulse_for_artifacts_dir(artifacts_dir)
    return marker_path


def _touch_shell_refresh_pulse_for_artifacts_dir(artifacts_dir: str) -> None:
    """Nudge artifact watchers after a pending handoff marker mutation."""
    try:
        from sase.shells.settlement import (
            project_name_from_artifacts_dir,
            touch_shell_refresh_pulse,
        )

        touch_shell_refresh_pulse(project_name_from_artifacts_dir(artifacts_dir))
    except Exception:  # noqa: BLE001 - a refresh pulse must never fail the handoff.
        pass


__all__ = [
    "ShellHandoffError",
    "maybe_handoff_shell_from_agent",
    "will_handoff_shell_to_agent_runner",
    "write_shell_pending_marker",
]
