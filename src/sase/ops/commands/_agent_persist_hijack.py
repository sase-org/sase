"""Durable ``sase ops agent persist-hijack`` operation helper.

Runs the ordered hijack stop orchestrator from a private request sidecar so
the TUI can submit a hijack as a proc that survives TUI exit. The payload
carries ``{"name": ..., "reason"?: ..., "action"?: "hijack"|"cancel"|"now"}``.
Cancel and force route to the same latch backends the TUI uses; the default
``hijack`` action still runs the stop orchestrator.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any

from sase.agent.hijack.stop import HijackStopResult, stop_agent_for_hijack
from sase.ops.cli import load_request
from sase.ops.names import AGENT_PERSIST_HIJACK

_LATCH_SUCCESS_VERDICTS = frozenset({"pending", "cancelled", "moot", "applied"})
_HIJACK_SUCCESS_STATUSES = frozenset(
    {
        "held",
        "latched",
        "pending",
        "cancelled",
        "finished_first",
        "moot",
        "applied",
    }
)
_MOOT_NOTICE = "finished before the hijack; nothing was held"


def run_persist_hijack(
    args: argparse.Namespace,
) -> tuple[bool, str, Mapping[str, Any]]:
    """Run one hijack stop, cancel, or force from the request sidecar payload."""
    request = load_request(AGENT_PERSIST_HIJACK, args, required=True)
    payload = dict(request.payload)
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("persist-hijack request payload requires a 'name'")
    action = payload.get("action") or "hijack"
    if not isinstance(action, str) or not action.strip():
        action = "hijack"
    action = action.strip().lower()
    if action in {"cancel", "now", "force"}:
        return _run_latch_action(action, payload, name)
    result: HijackStopResult = stop_agent_for_hijack(
        name,
        reason=payload.get("reason")
        if isinstance(payload.get("reason"), str)
        else None,
        hijack_id=payload.get("hijack_id")
        if isinstance(payload.get("hijack_id"), str)
        else None,
        source="persist_hijack",
    )
    return _from_stop_result(result)


def _run_latch_action(
    action: str, payload: Mapping[str, Any], name: str
) -> tuple[bool, str, Mapping[str, Any]]:
    from sase.agent.hijack.latch import cancel_latch, force_hijack_latch
    from sase.agent.hijack.ledger import target_key_for

    hijack_id = (
        payload.get("hijack_id") if isinstance(payload.get("hijack_id"), str) else None
    )
    target_key = (
        payload.get("target_key")
        if isinstance(payload.get("target_key"), str)
        else None
    )
    if not target_key:
        project_file = payload.get("project_file")
        session = payload.get("session_name") or name
        if isinstance(project_file, str) and isinstance(session, str):
            target_key = target_key_for(project_file, session)
    if not target_key:
        return (
            False,
            "persist-hijack cancel/force requires a target_key",
            {
                "action": "force" if action in {"now", "force"} else action,
                "status": "refused",
                "code": "target_key_missing",
                "notify": True,
                "severity": "warning",
            },
        )
    if action == "cancel":
        result = cancel_latch(target_key, hijack_id=hijack_id)
    else:
        result = force_hijack_latch(target_key, hijack_id=hijack_id)
    return _from_latch_result(action, result)


def _from_latch_result(
    action: str, result: Mapping[str, Any]
) -> tuple[bool, str, Mapping[str, Any]]:
    verdict = str(result.get("verdict") or "")
    raw_record = result.get("record")
    record: dict[str, Any] = raw_record if isinstance(raw_record, dict) else {}
    status = {
        "pending": "latched",
        "cancelled": "cancelled",
        "moot": "finished_first",
        "applied": str(record.get("state") or "applied"),
        "no_latch": "no_latch",
        "refused": "refused",
        "error": "error",
        "ownership_uncertain": "ownership_uncertain",
    }.get(verdict, verdict or "error")
    message = str(result.get("message") or "")
    if verdict == "moot":
        message = _MOOT_NOTICE
    success = verdict in _LATCH_SUCCESS_VERDICTS
    normalized_action = "force" if action in {"now", "force"} else action
    out: dict[str, Any] = {
        "action": normalized_action,
        "status": status,
        "verdict": verdict,
        "code": result.get("code"),
        "hijack_id": result.get("hijack_id") or record.get("hijack_id"),
        "target_key": result.get("target_key") or record.get("target_key"),
        "workspace_num": record.get("workspace_num"),
        "artifacts_dir": record.get("artifacts_dir"),
        "notify": True,
        "schedule_agents_refresh_source": (
            "hijack_recovery" if success else "hijack_error_recovery"
        ),
        "severity": None if success else "warning",
        "next_action": result.get("next_action"),
        "forced": result.get("forced"),
    }
    if record:
        out["record"] = record
    return success, message, out


def _from_stop_result(
    result: HijackStopResult,
) -> tuple[bool, str, Mapping[str, Any]]:
    record = result.record or {}
    status = result.status
    success = result.exit_code == 0 or status in _HIJACK_SUCCESS_STATUSES
    out: dict[str, Any] = {
        "action": "hijack",
        "status": status,
        "hijack_id": result.hijack_id,
        "reason": result.reason,
        "workspace_num": record.get("workspace_num"),
        "artifacts_dir": record.get("artifacts_dir"),
        "notify": status
        in {
            "held",
            "finished_first",
            "stop_failed",
            "latched",
            "pending",
            "cancelled",
            "moot",
            "applied",
        },
        "schedule_agents_refresh_source": "hijack_error_recovery"
        if result.exit_code == 1
        else "hijack_recovery",
        "severity": "error" if result.exit_code == 1 else None,
    }
    if record:
        out["record"] = record
    return success, result.message, out


__all__ = ["run_persist_hijack"]
