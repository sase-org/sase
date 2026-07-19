"""Notification-gate adapter for launch approval requests."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from sase.agent.launch_preview import LAUNCH_PREVIEW_FILE
from sase.agent.launch_request_response import dispatch_approved_launch_request
from sase.agent.launch_request_types import ApprovedLaunchDispatchResult


def execute_launch_gate_command(
    option_id: str,
    *,
    dispatch_request: Callable[[Path], ApprovedLaunchDispatchResult] = (
        dispatch_approved_launch_request
    ),
) -> int:
    """Entry point used only by the hashed scripts in a launch gate bundle."""
    try:
        raw_input = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"invalid command input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(raw_input, dict):
        print("launch command input must be an object", file=sys.stderr)
        return 2

    if option_id == "approve":
        try:
            with redirect_stdout(sys.stderr):
                dispatch = dispatch_request(Path.cwd())
        except Exception as exc:
            result: dict[str, Any] = {
                "action": "approve",
                "dispatch_status": "failed",
                "dispatch_error": str(exc),
            }
        else:
            result = {
                "action": "approve",
                "dispatch_status": "launched",
                "launched_count": dispatch.launched_count,
            }
    elif option_id == "reject":
        result = {"action": "reject"}
    elif option_id == "feedback":
        feedback = raw_input.get("feedback")
        if not isinstance(feedback, str) or not feedback.strip():
            print("feedback text is required", file=sys.stderr)
            return 2
        result = {"action": "reject", "feedback": feedback}
    else:
        print(f"unsupported launch option: {option_id}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


def launch_gate_spec(
    request: dict[str, Any],
    *,
    preview: str,
    source_surface: str,
    slot_count: int,
) -> dict[str, Any]:
    empty_input_schema = {
        "type": "object",
        "additionalProperties": False,
    }
    approve_result_schema = {
        "type": "object",
        "required": ["action", "dispatch_status"],
        "properties": {
            "action": {"const": "approve"},
            "dispatch_status": {"enum": ["launched", "failed"]},
            "launched_count": {"type": "integer", "minimum": 0},
            "dispatch_error": {"type": "string"},
        },
        "allOf": [
            {
                "if": {
                    "properties": {"dispatch_status": {"const": "launched"}},
                    "required": ["dispatch_status"],
                },
                "then": {"required": ["launched_count"]},
            },
            {
                "if": {
                    "properties": {"dispatch_status": {"const": "failed"}},
                    "required": ["dispatch_status"],
                },
                "then": {"required": ["dispatch_error"]},
            },
        ],
        "additionalProperties": False,
    }
    reject_result_schema = {
        "type": "object",
        "required": ["action"],
        "properties": {"action": {"const": "reject"}},
        "additionalProperties": False,
    }
    feedback_input_schema = {
        "type": "object",
        "required": ["feedback"],
        "properties": {"feedback": {"type": "string", "minLength": 1}},
        "additionalProperties": False,
    }
    feedback_result_schema = {
        "type": "object",
        "required": ["action", "feedback"],
        "properties": {
            "action": {"const": "reject"},
            "feedback": {"type": "string", "minLength": 1},
        },
        "additionalProperties": False,
    }
    options = [
        {
            "id": "approve",
            "label": "Approve",
            "icon": "✅",
            "command": {"argv": ["commands/approve"]},
            "input_schema": empty_input_schema,
            "result_schema": approve_result_schema,
        },
        {
            "id": "reject",
            "label": "Reject",
            "icon": "❌",
            "command": {"argv": ["commands/reject"]},
            "input_schema": empty_input_schema,
            "result_schema": reject_result_schema,
        },
        {
            "id": "feedback",
            "label": "Send Feedback",
            "icon": "💬",
            "command": {"argv": ["commands/feedback"]},
            "input_schema": feedback_input_schema,
            "result_schema": feedback_result_schema,
            "feedback": "required",
        },
    ]
    resources = [
        {
            "path": f"commands/{option_id}",
            "role": "command",
            "content": launch_gate_command_script(option_id),
        }
        for option_id in ("approve", "reject", "feedback")
    ]
    resources.append(
        {
            "path": LAUNCH_PREVIEW_FILE,
            "role": "preview",
            "content": preview,
        }
    )
    return {
        "schema_version": 3,
        "kind": "launch",
        "request_id": str(request["request_id"]),
        "producer": dict(request.get("requester", {})),
        "continuation_mode": "wait_for_launch",
        "payload": request,
        "presentation": {
            "notes": [
                f"Launch approval requested: {slot_count} slot"
                f"{'s' if slot_count != 1 else ''}",
                f"Source: {source_surface}",
            ],
            "tags": ["launch"],
            "files": [LAUNCH_PREVIEW_FILE],
            "preview": LAUNCH_PREVIEW_FILE,
            "action_data": {
                "source_surface": source_surface,
                "slot_count": str(slot_count),
            },
        },
        "query": "approve OR reject OR feedback",
        "primary_branch": ["approve"],
        "options": options,
        "resources": resources,
        "auto": False,
    }


def launch_gate_command_script(option_id: str) -> str:
    """Return the only command wrapper accepted by the launch adapter."""
    return (
        f"#!{sys.executable}\n"
        "from sase.agent.launch_request import execute_launch_gate_command\n"
        f"raise SystemExit(execute_launch_gate_command({option_id!r}))\n"
    )
