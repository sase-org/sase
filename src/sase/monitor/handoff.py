"""Handing a lane from the starter agent to the monitor it just started.

Split out of :mod:`sase.monitor.start`: a monitor started from inside an
agent takes the lane over by dropping a pending marker in the starter's own
artifacts dir and killing the agent runner, which is a concern of the
*starter*, not of the supervisor launch.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from sase.agent.pending_handoff import MONITOR_PENDING_MARKER
from sase.agent.pending_handoff_write import (
    PendingHandoffError,
    write_pending_handoff_marker,
)

from .models import MonitorError, MonitorRecord


def will_handoff_monitor_to_agent_runner() -> bool:
    """Return whether ``maybe_handoff_monitor_from_agent`` will kill this runner.

    ``kill_agent_runner_group()`` is ``NoReturn``, so any output a caller
    wants to show (a start summary, a ``--json`` envelope) must be emitted
    *before* calling ``maybe_handoff_monitor_from_agent`` -- not after, and
    not conditioned on its return value, which the process never lives to
    observe when this is true.
    """
    return bool(os.environ.get("SASE_AGENT"))


def maybe_handoff_monitor_from_agent(
    record: MonitorRecord,
    *,
    artifacts_dir: str | None = None,
) -> bool:
    """Write the in-agent monitor handoff marker and kill this runner.

    ``start_monitor()`` is shared by host-owned monitor starts and future CLI
    code.  The CLI should call this helper after a record is created; it is a
    no-op outside an agent process and terminates the current runner when
    ``SASE_AGENT`` is set.
    """
    if not os.environ.get("SASE_AGENT"):
        return False

    resolved_artifacts_dir = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not resolved_artifacts_dir:
        raise MonitorError(
            "cannot hand monitor to agent runner: SASE_ARTIFACTS_DIR is unset"
        )

    write_monitor_pending_marker(record, resolved_artifacts_dir)

    from sase.main.utils import kill_agent_runner_group

    kill_agent_runner_group(resolved_artifacts_dir)
    return True


def write_monitor_pending_marker(
    record: MonitorRecord,
    artifacts_dir: str,
    *,
    timestamp: float | None = None,
) -> Path:
    """Persist the pending monitor handoff marker for the runner to adopt."""
    marker_data: dict[str, str | float] = {
        "monitor_id": record.monitor_id,
        "member_artifacts_dir": record.artifacts_dir,
        "member_agent_name": record.member_agent_name,
    }
    if timestamp is not None:
        marker_data["timestamp"] = timestamp
    try:
        marker_path = write_pending_handoff_marker(
            MONITOR_PENDING_MARKER,
            marker_data,
            artifacts_dir=artifacts_dir,
        )
    except (OSError, PendingHandoffError) as exc:
        raise MonitorError(f"could not write monitor handoff marker: {exc}") from exc

    _touch_agent_artifacts_refresh_pulse(artifacts_dir)
    return marker_path


def _touch_agent_artifacts_refresh_pulse(artifacts_dir: str) -> None:
    try:
        pulse_path = Path(artifacts_dir).parents[1] / ".ace_refresh_pulse"
    except IndexError:
        return
    try:
        pulse_path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


__all__ = [
    "MONITOR_PENDING_MARKER",
    "maybe_handoff_monitor_from_agent",
    "will_handoff_monitor_to_agent_runner",
    "write_monitor_pending_marker",
]
