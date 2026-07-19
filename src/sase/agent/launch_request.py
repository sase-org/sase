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
    normalize_request_payload as _normalize_request_payload,
    preview_context as _preview_context,
    requester_context as _requester_context,
)
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
from sase.notification_gates.entrypoints import gate_command_entrypoint
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
    _preview_prompt, plan = _build_preview_plan(prompt)
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

    from sase.notification_gates.models import GateError
    from sase.notification_gates.service import create_gate

    try:
        gate = create_gate(
            _launch_gate_spec(
                request,
                preview=render_launch_preview_markdown(request),
                source_surface=source,
                slot_count=slot_count,
            )
        )
    except GateError as exc:
        raise LaunchRequestError(exc.code, exc.target, str(exc)) from exc
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
    )


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
    "read_launch_request",
    "running_agent_context_requires_launch_approval",
    "wait_for_launch_approval",
]
