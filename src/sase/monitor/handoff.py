"""Handing a lane from the starter agent to the monitor it just started.

Split out of :mod:`sase.monitor.start`: a monitor started from inside an
agent takes the lane over by dropping a pending marker in the starter's own
artifacts dir and killing the agent runner, which is a concern of the
*starter*, not of the supervisor launch.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sase.agent.pending_handoff import MONITOR_PENDING_MARKER
from sase.shells.handoff import (
    ShellHandoffError,
    maybe_handoff_shell_from_agent,
    will_handoff_shell_to_agent_runner,
    write_shell_pending_marker,
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
    return will_handoff_shell_to_agent_runner(os.environ)


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
    try:
        return maybe_handoff_shell_from_agent(
            marker_name=MONITOR_PENDING_MARKER,
            marker_data=_monitor_pending_payload(
                record,
                starter_artifacts_dir=resolved_artifacts_dir,
            ),
            artifacts_dir=resolved_artifacts_dir,
            env=os.environ,
        )
    except ShellHandoffError as exc:
        raise MonitorError(str(exc).replace("shell", "monitor")) from exc


def write_monitor_pending_marker(
    record: MonitorRecord,
    artifacts_dir: str,
    *,
    timestamp: float | None = None,
) -> Path:
    """Persist the pending monitor handoff marker for the runner to adopt."""
    try:
        return write_shell_pending_marker(
            MONITOR_PENDING_MARKER,
            _monitor_pending_payload(record, starter_artifacts_dir=artifacts_dir),
            artifacts_dir,
            timestamp=timestamp,
        )
    except ShellHandoffError as exc:
        raise MonitorError(str(exc).replace("shell", "monitor")) from exc


def _monitor_pending_payload(
    record: MonitorRecord,
    *,
    starter_artifacts_dir: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "monitor_id": record.monitor_id,
        "member_artifacts_dir": record.artifacts_dir,
        "member_agent_name": record.member_agent_name,
    }
    if starter_artifacts_dir:
        from sase.continuation_capture import publish_handoff_checkpoint_best_effort

        checkpoint_ref = publish_handoff_checkpoint_best_effort(
            starter_artifacts_dir,
            checkpoint_kind="monitor_handoff",
            payload={
                "monitor_id": record.monitor_id,
                "member_artifacts_dir": record.artifacts_dir,
                "member_agent_name": record.member_agent_name,
                "lane": record.lane,
                "project_name": record.project_name,
                "command": record.command,
                "cwd": record.cwd,
                "next_action": record.next_action,
                "next_model": record.next_model,
                "next_output": record.next_output,
                "request_fingerprint": record.request_fingerprint,
            },
        )
        if checkpoint_ref:
            payload["handoff_checkpoint_ref"] = checkpoint_ref
    return payload


__all__ = [
    "MONITOR_PENDING_MARKER",
    "maybe_handoff_monitor_from_agent",
    "will_handoff_monitor_to_agent_runner",
    "write_monitor_pending_marker",
]
