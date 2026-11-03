"""Pending-monitor marker writer kept for archived kill-path readers.

In-agent ``sase monitor start`` now stages and returns. This module still
writes the historical pending-marker shape so archived runs and runtime
retirement can interpret old handoffs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.agent.pending_handoff import MONITOR_PENDING_MARKER
from sase.turns.handoff import (
    TurnHandoffError,
    write_turn_pending_marker,
)

from .models import MonitorError, MonitorRecord


def write_monitor_pending_marker(
    record: MonitorRecord,
    artifacts_dir: str,
    *,
    timestamp: float | None = None,
) -> Path:
    """Persist the pending monitor handoff marker for the runner to adopt."""
    try:
        return write_turn_pending_marker(
            MONITOR_PENDING_MARKER,
            _monitor_pending_payload(record, starter_artifacts_dir=artifacts_dir),
            artifacts_dir,
            timestamp=timestamp,
            member="monitor turn",
        )
    except TurnHandoffError as exc:
        raise MonitorError(str(exc)) from exc


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
    "write_monitor_pending_marker",
]
