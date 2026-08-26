"""Pending-marker handoff from an agent runner to a family shell."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
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

    _touch_agent_artifacts_refresh_pulse(artifacts_dir)
    return marker_path


def _touch_agent_artifacts_refresh_pulse(artifacts_dir: str) -> None:
    """Nudge artifact watchers after a pending handoff marker mutation."""
    try:
        pulse_path = Path(artifacts_dir).parents[1] / ".ace_refresh_pulse"
    except IndexError:
        return
    try:
        pulse_path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


__all__ = [
    "ShellHandoffError",
    "maybe_handoff_shell_from_agent",
    "will_handoff_shell_to_agent_runner",
    "write_shell_pending_marker",
]
