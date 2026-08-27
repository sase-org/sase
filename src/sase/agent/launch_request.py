"""Host-side LaunchApproval request creation and approved dispatch.

This module is the stable public facade for launch approval requests.  The
planning, gate-adapter, and response-handling details live in focused sibling
modules.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.launch_preview import (
    build_launch_preview_request,
    render_launch_preview_markdown,
)
from sase.agent.launch_request_gate import (
    execute_launch_gate_command as _execute_launch_gate_command,
    launch_gate_command_script,
    launch_gate_spec as _launch_gate_spec,
)
from sase.agent.launch_request_planning import (
    build_preview_plan as _build_preview_plan,
    expand_prompt_for_typed_launch as _expand_prompt_for_typed_launch,
    normalize_request_payload as _normalize_request_payload,
    prepare_typed_launch_plan as _prepare_typed_launch_plan,
    preview_context as _preview_context,
    requester_context as _requester_context,
    resolve_typed_launch_selected_project as _resolve_typed_launch_selected_project,
    typed_launch_project_display_name as _typed_launch_project_display_name,
)
from sase.agent.launch_admission import stop_launch_admission
from sase.agent.launch_request_response import (
    cancel_launch_approval_request,
    dispatch_approved_launch_request,
    read_launch_request,
    wait_for_launch_approval,
)
from sase.agent.launch_request_types import (
    LAUNCH_REQUEST_SCHEMA_VERSION,
    LaunchRequestCreationResult,
    LaunchRequestError,
    LaunchRequestStatus,
)
from sase.gate_shell.models import GateShellError
from sase.notification_gates.entrypoints import gate_command_entrypoint
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import RESPONSE_FILENAME


def create_launch_approval_request_from_prompt(
    prompt: str,
    *,
    reason: str,
    approval: str = "required",
    max_slots: int = 1,
    source_surface: str | None = None,
) -> LaunchRequestCreationResult:
    """Create a pending LaunchApproval request from a prompt string."""
    return create_launch_approval_request(
        {
            "schema_version": LAUNCH_REQUEST_SCHEMA_VERSION,
            "prompt": prompt,
            "reason": reason,
            "approval": approval,
            "max_slots": max_slots,
        },
        source_surface=source_surface,
    )


def create_launch_approval_request(
    payload: Mapping[str, Any],
    *,
    source_surface: str | None = None,
) -> LaunchRequestCreationResult:
    """Build and durably register a neutral LaunchApproval gate."""
    normalized = _normalize_request_payload(payload)
    source = source_surface or _default_source_surface()
    prompt = str(normalized["prompt"])
    max_slots = int(normalized["max_slots"])
    preview_prompt, plan = _build_preview_plan(prompt)
    slot_count = len(plan.slots)
    if slot_count > max_slots:
        raise LaunchRequestError(
            "max_slots_exceeded",
            "max_slots",
            f"launch request plans {slot_count} slot(s), max_slots is {max_slots}",
        )

    context = _preview_context()
    request = build_launch_preview_request(
        plan=plan,
        context=context,
        source_surface=source,
        submitted_prompt=prompt,
        response_file=RESPONSE_FILENAME,
    )
    request["launch_request"] = normalized
    request["requester"] = _requester_context()
    request["dispatch"] = {
        "cwd": str(Path.cwd()),
        "prompt": prompt,
    }
    typed_plan = _typed_plan_payload(prompt)
    if typed_plan is not None:
        request["typed_plan"] = typed_plan
        request["plan_digest"] = typed_plan.get("content_digest")
        request["plan_schema_version"] = typed_plan.get("schema_version")
        selected_project = typed_plan.get("selected_project")
        if isinstance(selected_project, str) and selected_project:
            request["selected_project"] = selected_project
            display = _typed_launch_project_display_name(selected_project)
            if display:
                request["selected_project_display"] = display
        slot_count = len(typed_plan.get("units") or [])
        request["slot_count"] = slot_count
        if slot_count > max_slots:
            raise LaunchRequestError(
                "max_slots_exceeded",
                "max_slots",
                f"launch request plans {slot_count} slot(s), max_slots is {max_slots}",
            )

    gate_spec = _launch_gate_spec(
        request,
        preview=render_launch_preview_markdown(request),
        source_surface=source,
        slot_count=slot_count,
    )

    try:
        if running_agent_context_requires_launch_approval():
            from sase.gate_shell import create_gate_shell

            gate_shell_creation = create_gate_shell(_launch_shell_gate_spec(gate_spec))
            gate = gate_shell_creation.gate
        else:
            from sase.notification_gates.service import create_gate

            gate_shell_creation = None
            gate = create_gate(gate_spec)
    except GateError as exc:
        raise LaunchRequestError(exc.code, exc.target, str(exc)) from exc
    except GateShellError as exc:
        raise LaunchRequestError("gate_shell_failed", "shell", str(exc)) from exc
    if gate.notification_id is None:  # Launch auto-resolution is forbidden.
        raise LaunchRequestError(
            "invalid_state",
            str(gate.bundle_path),
            "launch approval gate has no notification id",
        )
    if gate.preview_path is None:
        raise LaunchRequestError(
            "invalid_state",
            str(gate.bundle_path),
            "launch approval gate has no preview",
        )
    return LaunchRequestCreationResult(
        request_id=str(request["request_id"]),
        notification_id=gate.notification_id,
        response_dir=gate.bundle_path,
        request_path=gate.request_path,
        preview_path=gate.preview_path,
        response_path=gate.response_path,
        request=request,
        gate_shell_creation=gate_shell_creation,
    )


def maybe_handoff_launch_approval_from_agent(
    request: LaunchRequestCreationResult,
    *,
    artifacts_dir: str | None = None,
) -> bool:
    """Hand an agent-side LaunchApproval request to its gate shell, if any."""
    creation = request.gate_shell_creation
    if creation is None or not creation.should_handoff:
        return False
    from sase.gate_shell import (
        maybe_handoff_gate_from_agent,
        will_handoff_gate_to_agent_runner,
    )

    if not will_handoff_gate_to_agent_runner():
        return False
    try:
        return maybe_handoff_gate_from_agent(creation, artifacts_dir=artifacts_dir)
    except GateShellError as exc:
        raise LaunchRequestError(
            "gate_shell_handoff_failed", "shell", str(exc)
        ) from exc


def _launch_shell_gate_spec(spec: dict[str, Any]) -> dict[str, Any]:
    shell_spec = dict(spec)
    shell_spec["shell"] = {
        "pending_status": "LAUNCH",
        "settled_status": "LAUNCHED",
        "accent": "#00D7D7",
        "workspace": "inherit",
        "next": {
            "fork": "family",
            "output": ["results"],
        },
        "branches": {
            "approve": {
                "status": "LAUNCHED",
                "accent": "#00D7D7",
                "prompt": None,
            },
            "reject": {
                "status": "LAUNCH REJECTED",
                "accent": "#FF5F5F",
                "prompt": None,
            },
            "timeout": {
                "status": "LAUNCH TIMED OUT",
                "accent": "#FFAF00",
                "prompt": None,
            },
            "stopped": {
                "status": "LAUNCH CANCELLED",
                "accent": "#FFAF00",
                "prompt": None,
            },
            "failed": {
                "status": "LAUNCH FAILED",
                "accent": "#FF5F5F",
                "prompt": None,
            },
        },
    }
    return shell_spec


def _typed_plan_payload(prompt: str) -> dict[str, Any] | None:
    from sase.xprompt.code_value import typed_launch_units_enabled

    if not typed_launch_units_enabled():
        return None
    expanded = _expand_prompt_for_typed_launch(prompt)
    selected_project = _resolve_typed_launch_selected_project(expanded)
    return _prepare_typed_launch_plan(expanded, selected_project=selected_project)


def running_agent_context_requires_launch_approval() -> bool:
    """Return whether this process is running inside an agent context."""
    return bool(os.environ.get("SASE_AGENT"))


@gate_command_entrypoint
def execute_launch_gate_command(option_id: str) -> int:
    """Run a generated launch gate command through the public facade."""
    return _execute_launch_gate_command(
        option_id,
        dispatch_request=dispatch_approved_launch_request,
    )


def _default_source_surface() -> str:
    return "agent_skill" if running_agent_context_requires_launch_approval() else "cli"


__all__ = [
    "LAUNCH_REQUEST_SCHEMA_VERSION",
    "LaunchRequestCreationResult",
    "LaunchRequestError",
    "LaunchRequestStatus",
    "cancel_launch_approval_request",
    "create_launch_approval_request",
    "create_launch_approval_request_from_prompt",
    "dispatch_approved_launch_request",
    "execute_launch_gate_command",
    "launch_gate_command_script",
    "maybe_handoff_launch_approval_from_agent",
    "read_launch_request",
    "running_agent_context_requires_launch_approval",
    "stop_launch_admission",
    "wait_for_launch_approval",
]
