"""Durable ``sase ops agent persist-recover`` operation helper."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any

from sase.agent.hijack.recover import recover_hijacked_agent
from sase.agent.hijack.recover_common import RecoveryResult
from sase.agent.hijack.recover_release import RELEASE_ACTIONS, recover_release_action
from sase.agents.cli_recover import recovery_exit_code
from sase.ops.cli import load_request
from sase.ops.commands.common import OperationCommandResult
from sase.ops.names import AGENT_PERSIST_RECOVER


def run_persist_recover(args: argparse.Namespace) -> OperationCommandResult:
    """Run the shared recovery executor with a pinned sidecar request."""
    request = load_request(AGENT_PERSIST_RECOVER, args, required=True)
    payload = dict(request.payload)
    name = _required_string(payload, "name")
    action = _required_string(payload, "action")
    if action not in {"continue", "escalate", "dismiss", "restart"}:
        raise ValueError(
            "persist-recover action must be 'continue', 'escalate', "
            "'restart', or 'dismiss'"
        )
    expected_hijack_id = _required_string(payload, "expected_hijack_id")
    expected_revision = payload.get("expected_revision")
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
        raise ValueError("persist-recover requires an integer expected_revision")
    model = _optional_string(payload, "model")
    prompt = _optional_string(payload, "prompt")
    if prompt is not None and action not in {"continue", "restart"}:
        raise ValueError(
            "persist-recover prompt is supported only with continue or restart"
        )
    if model is not None and action in RELEASE_ACTIONS:
        raise ValueError(
            "persist-recover model is supported only with continue or escalate"
        )
    discard_without_snapshot = payload.get("discard_without_snapshot", False)
    if discard_without_snapshot not in (False, True):
        raise ValueError("persist-recover discard_without_snapshot must be a boolean")
    if discard_without_snapshot and action not in RELEASE_ACTIONS:
        raise ValueError(
            "persist-recover discard_without_snapshot is supported only "
            "with restart or dismiss"
        )

    if action in RELEASE_ACTIONS:
        result = recover_release_action(
            name,
            action=action,
            prompt=prompt,
            discard_without_snapshot=bool(discard_without_snapshot),
            expected_hijack_id=expected_hijack_id,
            expected_revision=expected_revision,
        )
    else:
        result = recover_hijacked_agent(
            name,
            action=action,
            model=model,
            prompt=prompt,
            expected_hijack_id=expected_hijack_id,
            expected_revision=expected_revision,
        )
    exit_code = recovery_exit_code(result)
    message = result.message or _default_message(result)
    return OperationCommandResult(
        success=exit_code == 0,
        message=message,
        payload=_result_payload(action, result),
        exit_code=exit_code,
    )


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"persist-recover request payload requires '{key}'")
    return value.strip()


def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"persist-recover request field '{key}' must be a string")
    return value


def _result_payload(action: str, result: RecoveryResult) -> Mapping[str, Any]:
    detail = dict(result.detail)
    return {
        "action": action,
        "status": result.kind,
        "hijack_id": result.hijack_id,
        "revision": result.revision,
        "successor": result.successor,
        "launch_identity": result.launch_identity,
        "admission_request_id": result.admission_request_id,
        "concrete_target": result.concrete_target,
        "model_changed": result.model_changed,
        "detail": detail,
        "notify": result.kind not in {"launched", "already_resolved"},
        "schedule_agents_refresh_source": "hijack_recovery",
        "severity": "error" if recovery_exit_code(result) == 1 else None,
    }


def _default_message(result: RecoveryResult) -> str:
    if result.kind == "queued":
        return "Recovery is queued; the held workspace stays pinned until ownership transfers."
    if result.kind == "launched":
        return f"Recovery launched {result.successor or 'a successor'} in the held workspace."
    if result.kind == "already_resolved":
        return "The hijack was already resolved."
    if result.kind == "already_resolving":
        return "A recovery resolution is already in progress."
    return "Hijack recovery did not complete."


__all__ = ["run_persist_recover"]
