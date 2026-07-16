"""Host-side LaunchApproval request creation and approved dispatch."""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
from collections.abc import Mapping
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.agent.launch_preview import (
    LAUNCH_PREVIEW_FILE,
    LAUNCH_REQUEST_FILE,
    build_launch_preview_request,
    render_launch_preview_markdown,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.notification_gates.paths import REQUEST_FILENAME, RESPONSE_FILENAME

LAUNCH_REQUEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LaunchRequestCreationResult:
    request_id: str
    notification_id: str
    response_dir: Path
    request_path: Path
    preview_path: Path
    response_path: Path
    request: dict[str, Any]


LaunchRequestStatus = Literal[
    "approved",
    "rejected",
    "feedback",
    "dispatch_failed",
    "cancelled",
    "timed_out",
]


@dataclass(frozen=True)
class _LaunchRequestOutcome:
    """Deterministic terminal result observed by an agent-side requester."""

    status: LaunchRequestStatus
    request_id: str
    notification_id: str
    choice_id: str | None
    message: str
    response: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "request_id": self.request_id,
            "notification_id": self.notification_id,
            "choice_id": self.choice_id,
            "message": self.message,
            "response": self.response,
        }


@dataclass(frozen=True)
class _ApprovedLaunchDispatchResult:
    request_id: str
    results: list[AgentLaunchResult]

    @property
    def launched_count(self) -> int:
        return len(self.results)


class LaunchRequestError(RuntimeError):
    """Deterministic launch-request validation or dispatch failure."""

    def __init__(self, code: str, target: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.target = target


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


def wait_for_launch_approval(
    request: LaunchRequestCreationResult,
    *,
    poll_interval: float = 0.2,
) -> _LaunchRequestOutcome:
    """Wait mechanically for a launch gate and translate its neutral response."""
    from sase.notification_gates.models import GateError
    from sase.notification_gates.poller import wait_for_gate

    terminated = False
    previous_sigterm: Any = None

    def on_sigterm(signum: int, frame: object) -> None:
        del signum, frame
        nonlocal terminated
        terminated = True

    if threading.current_thread() is threading.main_thread():
        previous_sigterm = signal.signal(signal.SIGTERM, on_sigterm)
    try:
        result = wait_for_gate(
            request.response_dir,
            poll_interval=poll_interval,
            cancelled=lambda: terminated,
        )
    except GateError as exc:
        raise LaunchRequestError(exc.code, exc.target, str(exc)) from exc
    finally:
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
    if result.status != "responded":
        status: LaunchRequestStatus = (
            "timed_out" if result.status == "timed_out" else "cancelled"
        )
        return _LaunchRequestOutcome(
            status=status,
            request_id=request.request_id,
            notification_id=request.notification_id,
            choice_id=None,
            message=(
                "Launch approval timed out"
                if status == "timed_out"
                else "Launch approval cancelled"
            ),
            response=result.payload,
        )
    return _launch_outcome_from_response(request, result.payload)


def cancel_launch_approval_request(
    request: LaunchRequestCreationResult,
) -> dict[str, Any]:
    """Cancel a request that the requester no longer intends to wait for."""
    from sase.notification_gates.executor import cancel_gate
    from sase.notification_gates.models import GateError

    try:
        return cancel_gate(request.response_dir, source="launch_requester")
    except GateError as exc:
        raise LaunchRequestError(exc.code, exc.target, str(exc)) from exc


def dispatch_approved_launch_request(
    response_dir: Path,
) -> _ApprovedLaunchDispatchResult:
    """Dispatch a neutral launch bundle or an in-flight legacy request."""
    data = read_launch_request(response_dir)

    dispatch = data.get("dispatch")
    if not isinstance(dispatch, dict):
        raise LaunchRequestError(
            "invalid_request", "dispatch", "launch request has no dispatch payload"
        )
    prompt = dispatch.get("prompt")
    cwd = dispatch.get("cwd")
    if not isinstance(prompt, str) or not prompt.strip():
        raise LaunchRequestError(
            "invalid_request", "dispatch.prompt", "dispatch prompt is missing"
        )
    if not isinstance(cwd, str) or not cwd:
        raise LaunchRequestError(
            "invalid_request", "dispatch.cwd", "dispatch cwd is missing"
        )

    cwd_path = Path(cwd).expanduser()
    if not cwd_path.is_dir():
        raise LaunchRequestError(
            "invalid_request", "dispatch.cwd", f"dispatch cwd does not exist: {cwd}"
        )

    original_cwd = Path.cwd()
    try:
        os.chdir(cwd_path)
        from sase.agent import launcher as launcher_mod

        results = launcher_mod.launch_agents_from_cwd(prompt)
    finally:
        os.chdir(original_cwd)

    return _ApprovedLaunchDispatchResult(
        request_id=str(data.get("request_id") or ""),
        results=results,
    )


def read_launch_request(response_dir: Path) -> dict[str, Any]:
    """Read a neutral launch payload first, then the legacy request file."""
    neutral_path = response_dir / REQUEST_FILENAME
    legacy_path = response_dir / LAUNCH_REQUEST_FILE
    request_path = neutral_path if neutral_path.is_file() else legacy_path
    try:
        data = json.loads(request_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LaunchRequestError(
            "invalid_request", str(request_path), "launch request is missing"
        ) from exc
    except json.JSONDecodeError as exc:
        raise LaunchRequestError(
            "invalid_request", str(request_path), "launch request is not valid JSON"
        ) from exc
    if not isinstance(data, dict):
        raise LaunchRequestError(
            "invalid_request", str(request_path), "launch request must be an object"
        )

    if request_path == neutral_path:
        if data.get("kind") != "launch":
            raise LaunchRequestError(
                "invalid_request", str(request_path), "gate is not a launch request"
            )
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise LaunchRequestError(
                "invalid_request",
                str(request_path),
                "launch gate payload must be an object",
            )
        return payload
    return data


def execute_launch_gate_command(choice: str) -> int:
    """Entry point used only by the hashed scripts in a launch gate bundle."""
    try:
        raw_input = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"invalid command input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(raw_input, dict):
        print("launch command input must be an object", file=sys.stderr)
        return 2

    if choice == "approve":
        try:
            with redirect_stdout(sys.stderr):
                dispatch = dispatch_approved_launch_request(Path.cwd())
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
    elif choice == "reject":
        result = {"action": "reject"}
    elif choice == "feedback":
        feedback = raw_input.get("feedback")
        if not isinstance(feedback, str) or not feedback.strip():
            print("feedback text is required", file=sys.stderr)
            return 2
        result = {"action": "reject", "feedback": feedback}
    else:
        print(f"unsupported launch choice: {choice}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


def _launch_outcome_from_response(
    request: LaunchRequestCreationResult, response: dict[str, Any]
) -> _LaunchRequestOutcome:
    choice_id = response.get("choice_id")
    result = response.get("result")
    if not isinstance(choice_id, str) or not isinstance(result, dict):
        raise LaunchRequestError(
            "invalid_response",
            str(request.response_path),
            "launch response is missing choice_id or result",
        )
    if choice_id == "approve":
        if result.get("dispatch_status") == "failed":
            status: LaunchRequestStatus = "dispatch_failed"
            message = str(result.get("dispatch_error") or "Launch dispatch failed")
        elif result.get("dispatch_status") == "launched":
            status = "approved"
            count = int(result.get("launched_count") or 0)
            message = (
                f"Launch approved and dispatched {count} agent"
                f"{'s' if count != 1 else ''}"
            )
        else:
            raise LaunchRequestError(
                "invalid_response",
                str(request.response_path),
                "approved launch response has no dispatch status",
            )
    elif choice_id == "reject":
        status = "rejected"
        message = "Launch rejected"
    elif choice_id == "feedback":
        status = "feedback"
        message = "Launch rejected with feedback"
    else:
        raise LaunchRequestError(
            "invalid_response",
            str(request.response_path),
            f"unsupported launch response choice: {choice_id}",
        )
    return _LaunchRequestOutcome(
        status=status,
        request_id=request.request_id,
        notification_id=request.notification_id,
        choice_id=choice_id,
        message=message,
        response=response,
    )


def _launch_gate_spec(
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
    choices = [
        {
            "id": "approve",
            "label": "Approve",
            "command": {"argv": ["commands/approve"]},
            "input_schema": empty_input_schema,
            "result_schema": approve_result_schema,
        },
        {
            "id": "reject",
            "label": "Reject",
            "command": {"argv": ["commands/reject"]},
            "input_schema": empty_input_schema,
            "result_schema": reject_result_schema,
        },
        {
            "id": "feedback",
            "label": "Send Feedback",
            "command": {"argv": ["commands/feedback"]},
            "input_schema": feedback_input_schema,
            "result_schema": feedback_result_schema,
        },
    ]
    resources = [
        {
            "path": f"commands/{choice}",
            "role": "command",
            "content": launch_gate_command_script(choice),
        }
        for choice in ("approve", "reject", "feedback")
    ]
    resources.append(
        {
            "path": LAUNCH_PREVIEW_FILE,
            "role": "preview",
            "content": preview,
        }
    )
    return {
        "schema_version": 1,
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
        "choices": choices,
        "resources": resources,
        "auto": False,
    }


def launch_gate_command_script(choice: str) -> str:
    """Return the only command wrapper accepted by the launch adapter."""
    return (
        f"#!{sys.executable}\n"
        "from sase.agent.launch_request import execute_launch_gate_command\n"
        f"raise SystemExit(execute_launch_gate_command({choice!r}))\n"
    )


def running_agent_context_requires_launch_approval() -> bool:
    """Return whether this process is running inside an agent context."""
    return bool(os.environ.get("SASE_AGENT"))


def _normalize_request_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    schema_version = payload.get("schema_version")
    if schema_version != LAUNCH_REQUEST_SCHEMA_VERSION:
        raise LaunchRequestError(
            "invalid_schema",
            "schema_version",
            f"schema_version must be {LAUNCH_REQUEST_SCHEMA_VERSION}",
        )

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise LaunchRequestError("invalid_request", "prompt", "prompt is required")

    reason = payload.get("reason")
    if reason is None:
        reason = "Detached launch requested."
    if not isinstance(reason, str) or not reason.strip():
        raise LaunchRequestError("invalid_request", "reason", "reason is required")

    approval = payload.get("approval", "required")
    if approval != "required":
        raise LaunchRequestError(
            "unsupported_approval",
            "approval",
            "only approval='required' is supported",
        )

    raw_max_slots = payload.get("max_slots", 1)
    try:
        max_slots = int(raw_max_slots)
    except (TypeError, ValueError) as exc:
        raise LaunchRequestError(
            "invalid_request", "max_slots", "max_slots must be an integer"
        ) from exc
    if max_slots < 1:
        raise LaunchRequestError(
            "invalid_request", "max_slots", "max_slots must be at least 1"
        )

    normalized: dict[str, Any] = {
        "schema_version": LAUNCH_REQUEST_SCHEMA_VERSION,
        "prompt": prompt,
        "reason": reason,
        "approval": approval,
        "max_slots": max_slots,
    }
    family_type = payload.get("family_type")
    if family_type is not None:
        if not isinstance(family_type, str) or not family_type.strip():
            raise LaunchRequestError(
                "invalid_request", "family_type", "family_type must be a string"
            )
        normalized["family_type"] = family_type
    return normalized


def _build_preview_plan(prompt: str) -> tuple[str, Any]:
    from sase.agent.xprompt_swarm import expand_xprompt_swarms_with_metadata
    from sase.agent.multi_prompt import parse_multi_prompt
    from sase.project_aliases import canonicalize_project_aliases_in_prompt
    from sase.xprompt._parsing import (
        normalize_default_vcs_workflow,
        normalize_default_vcs_workflow_segment,
    )

    submitted = canonicalize_project_aliases_in_prompt(prompt)
    multi = parse_multi_prompt(submitted)
    expanded_records = expand_xprompt_swarms_with_metadata(
        multi.segments, multi.local_xprompts
    )
    expanded_segments = [record.prompt for record in expanded_records]
    if len(expanded_segments) > 1:
        from sase.core.agent_launch_facade import plan_fake_fanout

        normalized_segments = [
            normalize_default_vcs_workflow_segment(segment)
            for segment in expanded_segments
        ]
        return "\n---\n".join(normalized_segments), plan_fake_fanout(
            "multi_prompt", normalized_segments
        )

    query = normalize_default_vcs_workflow(expanded_segments[0])

    from sase.core.agent_launch_facade import plan_agent_launch_fanout, plan_fake_fanout

    repeat_plan = plan_agent_launch_fanout(query, launch_kind="repeat")
    if repeat_plan.slots:
        return query, repeat_plan

    from sase.xprompt.directives import plan_prompt_fanout_variants

    fanout_plan = plan_prompt_fanout_variants(query)
    if fanout_plan is None and "#" in query:
        from sase.xprompt.processor import (
            process_xprompt_references,
            prompt_may_reference_xprompt,
        )

        if prompt_may_reference_xprompt(query):
            expanded = process_xprompt_references(query)
            fanout_plan = plan_prompt_fanout_variants(expanded)
    if fanout_plan is not None:
        return query, fanout_plan
    return query, plan_fake_fanout("single", [query])


def _preview_context() -> Any:
    from sase.agent.launch_executor import LaunchExecutionContext
    from sase.core.paths import sase_projects_dir
    from sase.main.utils import ensure_project_file_and_get_workspace_num

    project_file, workspace_num, project_name = (
        ensure_project_file_and_get_workspace_num(create_missing=False)
    )
    is_home_mode = project_file is None
    if is_home_mode:
        from sase.ace.changespec.project_spec_path import preferred_project_spec_path

        project_name = "home"
        home_dir = str(sase_projects_dir() / "home")
        project_file = preferred_project_spec_path(home_dir, "home")
        workspace_num = 0

    assert project_file is not None
    assert project_name is not None
    return LaunchExecutionContext(
        cl_name=project_name,
        project_file=project_file,
        project_name=project_name,
        is_home_mode=is_home_mode,
        workspace_num=workspace_num,
        workspace_dir=str(Path.cwd()) if is_home_mode else None,
    )


def _requester_context() -> dict[str, str]:
    keys = (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_ARTIFACTS_DIR",
        "SASE_AGENT_WORKFLOW_NAME",
    )
    return {key: value for key in keys if (value := os.environ.get(key))}


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
