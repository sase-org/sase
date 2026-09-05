"""Option-query gates for workflow human-in-the-loop review."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.notification_gates.entrypoints import (
    gate_command_entrypoint,
    python_gate_command_script,
)
from sase.notification_gates.models import GateError
from sase.xprompt.workflow_executor_types import HITLResult

HITL_CONTINUATION_MODE = "agent_hitl"


def _hitl_gate_option_ids(step_type: str, *, has_output: bool) -> tuple[str, ...]:
    """Return the existing HITL actions available for one workflow step."""
    options = ["accept"]
    if step_type == "agent" or (step_type in {"bash", "python"} and has_output):
        options.append("edit")
    if step_type == "agent":
        options.append("feedback")
    elif step_type in {"bash", "python"}:
        options.append("rerun")
    options.append("reject")
    return tuple(options)


def create_workflow_hitl_gate(
    *,
    step_name: str,
    step_type: str,
    output: Any,
    workflow_name: str,
    artifacts_dir: str,
    has_output: bool,
    output_types: Mapping[str, str] | None,
    timeout_seconds: float,
) -> Any:
    """Create a singleton-branch gate for a workflow review."""
    spec = _workflow_hitl_gate_spec(
        step_name=step_name,
        step_type=step_type,
        output=output,
        workflow_name=workflow_name,
        artifacts_dir=artifacts_dir,
        has_output=has_output,
        output_types=output_types,
        timeout_seconds=timeout_seconds,
    )
    from sase.notification_gates.service import create_gate

    return create_gate(spec)


def create_workflow_hitl_shell_gate(
    *,
    step_name: str,
    step_type: str,
    output: Any,
    workflow_name: str,
    artifacts_dir: str,
    has_output: bool,
    output_types: Mapping[str, str] | None,
    timeout_seconds: float,
) -> Any:
    """Create a shell-backed HITL gate whose follow-up continues the workflow."""
    spec = _workflow_hitl_gate_spec(
        step_name=step_name,
        step_type=step_type,
        output=output,
        workflow_name=workflow_name,
        artifacts_dir=artifacts_dir,
        has_output=has_output,
        output_types=output_types,
        timeout_seconds=timeout_seconds,
    )
    spec["shell"] = _workflow_hitl_shell_spec(
        step_name=step_name,
        step_type=step_type,
        workflow_name=workflow_name,
        option_ids=tuple(str(option["id"]) for option in spec["options"]),
    )
    from sase.gate_shell import create_gate_shell

    return create_gate_shell(spec)


def maybe_handoff_workflow_hitl_from_agent(creation: Any) -> bool:
    """Hand a shell-backed workflow HITL gate to the agent runner."""
    if not getattr(creation, "should_handoff", False):
        return False
    from sase.gate_shell import (
        maybe_handoff_gate_from_agent,
        will_handoff_gate_to_agent_runner,
    )

    if not will_handoff_gate_to_agent_runner():
        return False
    return maybe_handoff_gate_from_agent(creation)


def _workflow_hitl_gate_spec(
    *,
    step_name: str,
    step_type: str,
    output: Any,
    workflow_name: str,
    artifacts_dir: str,
    has_output: bool,
    output_types: Mapping[str, str] | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Return the durable gate specification for one workflow HITL review."""
    option_ids = _hitl_gate_option_ids(step_type, has_output=has_output)
    return {
        "schema_version": 3,
        "kind": "hitl",
        "request_id": f"hitl-{uuid4()}",
        "producer": {"artifacts_dir": artifacts_dir},
        "continuation_mode": HITL_CONTINUATION_MODE,
        "gate_timeout_seconds": timeout_seconds,
        "payload": {
            "step_name": step_name,
            "step_type": step_type,
            "output": _json_safe(output),
            "workflow_name": workflow_name,
            "has_output": has_output,
            "output_types": dict(output_types or {}),
        },
        "presentation": {
            "notes": [f"HITL waiting: step '{step_name}' in {workflow_name}"],
            "tags": ["hitl"],
            "action_data": {"workflow_name": workflow_name},
        },
        "query": " OR ".join(option_ids),
        "primary_branch": ["accept"],
        "options": [_hitl_gate_option(option_id) for option_id in option_ids],
        "resources": [
            {
                "path": f"commands/{option_id}",
                "role": "command",
                "content": _hitl_gate_command_script(option_id),
            }
            for option_id in option_ids
        ],
        "auto": False,
    }


def wait_for_workflow_hitl_gate(bundle_path: Path) -> HITLResult:
    """Wait for a workflow gate and translate its selected option."""
    from sase.notification_gates.models import GateError
    from sase.notification_gates.poller import poll_gate

    poll_interval = 0.2
    if poll_interval <= 0:
        raise GateError(
            "invalid_poll_interval", "poll_interval", "poll_interval must be positive"
        )
    while True:
        result = poll_gate(bundle_path)
        if result is not None:
            break
        time.sleep(poll_interval)
    if result.status != "responded":
        return HITLResult(action="reject", approved=False)
    return _translate_workflow_hitl_response(result.payload)


def workflow_hitl_should_handoff_from_agent() -> bool:
    """Return whether workflow HITL should be represented as a gate shell."""
    return bool(os.environ.get("SASE_AGENT"))


def _workflow_hitl_shell_spec(
    *,
    step_name: str,
    step_type: str,
    workflow_name: str,
    option_ids: tuple[str, ...],
) -> dict[str, Any]:
    branches = {
        option_id: _workflow_hitl_branch(
            option_id,
            step_name=step_name,
            step_type=step_type,
            workflow_name=workflow_name,
        )
        for option_id in option_ids
    }
    branches.update(
        {
            "timeout": {
                "status": "HITL TIMED OUT",
                "accent": "#FFAF00",
                "prompt": None,
            },
            "stopped": {
                "status": "HITL CANCELLED",
                "accent": "#FFAF00",
                "prompt": None,
            },
            "failed": {
                "status": "HITL FAILED",
                "accent": "#FF5F5F",
                "prompt": None,
            },
        }
    )
    return {
        "pending_status": "HITL",
        "settled_status": "HITL DONE",
        "accent": "#F8AD08",
        "workspace": "inherit",
        "next": {"fork": "family", "output": ["results"]},
        "branches": branches,
    }


def _workflow_hitl_branch(
    option_id: str,
    *,
    step_name: str,
    step_type: str,
    workflow_name: str,
) -> dict[str, Any]:
    status, accent = {
        "accept": ("HITL ACCEPTED", "#00D7AF"),
        "edit": ("HITL EDITED", "#00D7AF"),
        "feedback": ("HITL FEEDBACK", "#6FC4FF"),
        "rerun": ("HITL RERUN", "#6FC4FF"),
        "reject": ("HITL REJECTED", "#FF5F5F"),
    }[option_id]
    branch: dict[str, Any] = {"status": status, "accent": accent}
    if option_id == "reject":
        branch["prompt"] = None
    else:
        branch["prompt"] = _workflow_hitl_followup_prompt(
            option_id,
            step_name=step_name,
            step_type=step_type,
            workflow_name=workflow_name,
        )
    return branch


def _workflow_hitl_followup_prompt(
    option_id: str,
    *,
    step_name: str,
    step_type: str,
    workflow_name: str,
) -> str:
    action = {
        "accept": "Continue with the accepted step output.",
        "edit": "Continue with the edited output in the selected option result.",
        "feedback": "Continue from the reviewer feedback in the gate result.",
        "rerun": "Rerun the reviewed command step, then continue.",
    }[option_id]
    return "\n".join(
        [
            f"Continue workflow `{workflow_name}` after HITL review.",
            "",
            f"Step: `{step_name}`",
            f"Step type: `{step_type}`",
            f"HITL action: `{option_id}`",
            "",
            action,
            "Use the gate Results section as the authoritative HITL result.",
        ]
    )


def _translate_workflow_hitl_response(response: Mapping[str, Any]) -> HITLResult:
    """Translate a uniform v2 response into the workflow runner protocol."""
    raw_selected = response.get("selected_option_ids")
    option_results = response.get("option_results")
    if (
        not isinstance(raw_selected, list)
        or len(raw_selected) != 1
        or not isinstance(raw_selected[0], str)
        or not isinstance(option_results, list)
    ):
        raise GateError(
            "invalid_response",
            "selected_option_ids",
            "HITL response must select exactly one option",
        )
    option_id = raw_selected[0]
    command_result = next(
        (
            entry.get("result")
            for entry in option_results
            if isinstance(entry, Mapping) and entry.get("id") == option_id
        ),
        None,
    )
    if not isinstance(command_result, Mapping):
        raise GateError(
            "invalid_response",
            "option_results",
            "HITL response is missing its selected option result",
        )
    if option_id == "accept":
        return HITLResult(action="accept", approved=True)
    if option_id == "reject":
        return HITLResult(action="reject", approved=False)
    if option_id == "edit":
        return HITLResult(
            action="edit", edited_output=command_result.get("edited_output")
        )
    if option_id == "feedback":
        feedback = response.get("feedback")
        return HITLResult(
            action="feedback",
            approved=False,
            feedback=feedback if isinstance(feedback, str) else None,
        )
    if option_id == "rerun":
        return HITLResult(action="rerun")
    raise GateError(
        "invalid_response", option_id, f"unsupported HITL response option: {option_id}"
    )


def _hitl_gate_command_script(option_id: str) -> str:
    """Return the adapter-owned command wrapper for a HITL option."""
    return python_gate_command_script(
        "from sase.xprompt.workflow_hitl_gate import execute_hitl_gate_command\n"
        f"raise SystemExit(execute_hitl_gate_command({option_id!r}))\n"
    )


@gate_command_entrypoint
def execute_hitl_gate_command(option_id: str) -> int:
    """Emit the workflow protocol fragment for one selected HITL option."""
    try:
        raw_input = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"invalid command input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(raw_input, dict):
        print("HITL command input must be an object", file=sys.stderr)
        return 2
    if option_id == "accept":
        result = {"action": "accept", "approved": True}
    elif option_id == "reject":
        result = {"action": "reject", "approved": False}
    elif option_id == "edit":
        if "edited_output" not in raw_input:
            print("edited_output is required", file=sys.stderr)
            return 2
        result = {"action": "edit", "edited_output": raw_input["edited_output"]}
    elif option_id == "feedback":
        result = {"action": "feedback", "approved": False}
    elif option_id == "rerun":
        result = {"action": "rerun"}
    else:
        print(f"unsupported HITL option: {option_id}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


def _hitl_gate_option(option_id: str) -> dict[str, Any]:
    label, icon = {
        "accept": ("Accept and continue", "✅"),
        "edit": ("Edit output", "✏️"),
        "feedback": ("Provide feedback", "💬"),
        "rerun": ("Re-run command", "🔄"),
        "reject": ("Reject and abort workflow", "❌"),
    }[option_id]
    input_properties: dict[str, Any] = {
        "action": {"type": "string"},
        "approved": {"type": "boolean"},
    }
    required: list[str] = []
    if option_id == "edit":
        input_properties["edited_output"] = {}
        required.append("edited_output")
    result_properties: dict[str, Any] = {"action": {"const": option_id}}
    result_required = ["action"]
    if option_id in {"accept", "reject", "feedback"}:
        result_properties["approved"] = {"type": "boolean"}
        result_required.append("approved")
    if option_id == "edit":
        result_properties["edited_output"] = {}
        result_required.append("edited_output")
    return {
        "id": option_id,
        "label": label,
        "icon": icon,
        "command": {"argv": [f"commands/{option_id}"]},
        "input_schema": {
            "type": "object",
            "required": required,
            "properties": input_properties,
            "additionalProperties": False,
        },
        "result_schema": {
            "type": "object",
            "required": result_required,
            "properties": result_properties,
            "additionalProperties": False,
        },
        "feedback": "required" if option_id == "feedback" else "disabled",
    }


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


__all__ = [
    "HITL_CONTINUATION_MODE",
    "create_workflow_hitl_gate",
    "create_workflow_hitl_shell_gate",
    "execute_hitl_gate_command",
    "maybe_handoff_workflow_hitl_from_agent",
    "wait_for_workflow_hitl_gate",
    "workflow_hitl_should_handoff_from_agent",
]
