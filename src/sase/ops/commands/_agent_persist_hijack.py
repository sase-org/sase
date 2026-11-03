"""Durable ``sase ops agent persist-hijack`` operation helper.

Runs the ordered hijack stop orchestrator from a private request sidecar so
the TUI can submit a hijack as a proc that survives TUI exit. The payload
carries ``{"name": ..., "reason"?: ...}``; the orchestrator owns flag gating,
eligibility, and the ledger transitions.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any

from sase.agent.hijack.stop import HijackStopResult, stop_agent_for_hijack
from sase.ops.cli import load_request
from sase.ops.names import AGENT_PERSIST_HIJACK


def run_persist_hijack(
    args: argparse.Namespace,
) -> tuple[bool, str, Mapping[str, Any]]:
    """Run one hijack stop from the request sidecar payload."""
    request = load_request(AGENT_PERSIST_HIJACK, args, required=True)
    payload = dict(request.payload)
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("persist-hijack request payload requires a 'name'")
    reason = payload.get("reason")
    result: HijackStopResult = stop_agent_for_hijack(
        name,
        reason=reason if isinstance(reason, str) else None,
        hijack_id=payload.get("hijack_id")
        if isinstance(payload.get("hijack_id"), str)
        else None,
        source="persist_hijack",
    )
    record = result.record or {}
    out: dict[str, Any] = {
        "action": "hijack",
        "status": result.status,
        "hijack_id": result.hijack_id,
        "reason": result.reason,
        "workspace_num": record.get("workspace_num"),
        "artifacts_dir": record.get("artifacts_dir"),
        "notify": result.status in {"held", "finished_first", "stop_failed"},
        "schedule_agents_refresh_source": "hijack_error_recovery"
        if result.exit_code != 0
        else "hijack_recovery",
        "severity": "error" if result.exit_code == 1 else None,
    }
    return result.exit_code == 0, result.message, out


__all__ = ["run_persist_hijack"]
