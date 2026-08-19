"""The resolved monitor-start request and the identity derived from it.

Split out of :mod:`sase.monitor.start` so the request type, its defaults, and
the fingerprint that decides whether two starts are "the same request" live
next to each other, away from the process/claim machinery that acts on them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256

from sase.monitor_status import (
    DEFAULT_MONITOR_START_STATUS as DEFAULT_START_STATUS,
    DEFAULT_MONITOR_STOP_STATUS as DEFAULT_STOP_STATUS,
)

from .followup_prompt import DEFAULT_NEXT_OUTPUT
from .models import MonitorRecord

DEFAULT_TAIL_LINES = 200
DEFAULT_TIMEOUT_SECONDS = 3600.0
DEFAULT_REASON = "run command"


@dataclass(frozen=True)
class StartMonitorRequest:
    """Fully-resolved request to start one monitor.

    ``project_name`` and ``cwd`` are resolved by the caller (the CLI or the
    host epic-launch path). An omitted ``lane`` is an implicit start: the
    exact ``SASE_AGENT_NAME`` caller is selected first, and the durable
    family is derived from that artifact. An explicit ``lane`` still
    targets an existing family the way host epic launch and ``--agent``
    do today.
    """

    command: str
    reason: str
    timeout_seconds: float
    cwd: str
    project_name: str
    lane: str | None = None
    label: str | None = None
    next_action: str | None = None
    start_status: str = DEFAULT_START_STATUS
    stop_status: str = DEFAULT_STOP_STATUS
    tail_lines: int = DEFAULT_TAIL_LINES
    idle_timeout_seconds: float = 0.0
    next_output: str = DEFAULT_NEXT_OUTPUT
    inherit_lane_workspace_claim: bool = True
    transfer_claim_from_pid: int | None = None


def default_label(command: str) -> str:
    """Return the label a request without an explicit one gets."""
    head = command.strip().split(maxsplit=1)[0] if command.strip() else command
    return head[:48]


def monitor_request_fingerprint(
    request: StartMonitorRequest,
    *,
    lane: str,
    label: str,
) -> str:
    """Return the stable identity of *request* on *lane*.

    Two starts with the same fingerprint are the same request, so a replay
    can return the existing monitor instead of raising a conflict.
    """
    payload = {
        "command": request.command,
        "cwd": request.cwd,
        "idle_timeout_seconds": request.idle_timeout_seconds,
        "inherit_lane_workspace_claim": request.inherit_lane_workspace_claim,
        "label": label,
        "lane": lane,
        "next_action": request.next_action or None,
        "next_output": request.next_output,
        "project_name": request.project_name,
        "reason": request.reason,
        "start_status": request.start_status,
        "stop_status": request.stop_status,
        "tail_lines": request.tail_lines,
        "timeout_seconds": request.timeout_seconds,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def active_monitor_message(
    lane: str,
    existing_record: MonitorRecord,
    *,
    requested_fingerprint: str,
    requested_command: str,
) -> str:
    """Explain why *existing_record* blocks a new start on *lane*."""
    if existing_record.command == requested_command:
        existing_fingerprint = (
            existing_record.request_fingerprint or "missing fingerprint"
        )
        return (
            f"lane {lane!r} already has an active monitor "
            f"({existing_record.monitor_id}) with the same command but a "
            "different request "
            f"(existing {existing_fingerprint}, requested {requested_fingerprint})"
        )
    return (
        f"lane {lane!r} already has an active monitor "
        f"({existing_record.monitor_id}): {existing_record.command!r}"
    )


__all__ = [
    "DEFAULT_REASON",
    "DEFAULT_START_STATUS",
    "DEFAULT_STOP_STATUS",
    "DEFAULT_TAIL_LINES",
    "DEFAULT_TIMEOUT_SECONDS",
    "StartMonitorRequest",
    "active_monitor_message",
    "default_label",
    "monitor_request_fingerprint",
]
