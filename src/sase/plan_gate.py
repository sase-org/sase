"""Tiered command-backed plan approval gates."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast

from sase.notification_gates.entrypoints import gate_command_entrypoint
from sase.notification_gates.models import GateError

PLAN_EDIT_OPERATION_ID = "edit_plan"
PLAN_RESOURCE_PATH = "plan.md"
PLAN_CONTINUATION_MODE = "agent_plan"

PlanGateTier = Literal["tale", "epic"]


def create_plan_approval_gate(
    plan_file: str | Path,
    session_id: str,
    *,
    auto_enabled: bool = False,
    auto_argument: str | None = None,
    agent_name: str | None = None,
    agent_model: str | None = None,
    agent_llm_provider: str | None = None,
    agent_runtime: str | None = None,
    agent_vcs_tag: str | None = None,
) -> Any:
    """Create a ``PlanApproval`` or ``EpicApproval`` gate by authored tier."""
    plan_path = Path(plan_file).expanduser()
    from sase.sdd.plan_tiers import read_plan_tier

    tier = read_plan_tier(plan_path)
    if tier not in {"tale", "epic"}:
        raise GateError(
            "invalid_plan_tier",
            str(plan_path),
            "plan frontmatter must declare tier: tale or tier: epic",
        )

    typed_tier = cast(PlanGateTier, tier)
    if auto_enabled:
        validate_plan_auto_argument(typed_tier, auto_argument)
    from sase.plan_approval_actions import require_plan_approval_validation

    require_plan_approval_validation(plan_path, typed_tier)
    from sase.notification_gates.service import create_gate

    return create_gate(
        _build_plan_gate_spec(
            plan_path,
            session_id,
            tier=typed_tier,
            auto_enabled=auto_enabled,
            auto_argument=auto_argument,
            agent_name=agent_name,
            agent_model=agent_model,
            agent_llm_provider=agent_llm_provider,
            agent_runtime=agent_runtime,
            agent_vcs_tag=agent_vcs_tag,
        )
    )


def _build_plan_gate_spec(
    plan_file: Path,
    session_id: str,
    *,
    tier: PlanGateTier,
    auto_enabled: bool,
    auto_argument: str | None,
    agent_name: str | None,
    agent_model: str | None,
    agent_llm_provider: str | None,
    agent_runtime: str | None,
    agent_vcs_tag: str | None,
) -> dict[str, Any]:
    """Build the only request shape accepted by the plan adapters."""
    action_data = _plan_action_data(
        session_id=session_id,
        agent_name=agent_name,
        agent_model=agent_model,
        agent_llm_provider=agent_llm_provider,
        agent_runtime=agent_runtime,
        agent_vcs_tag=agent_vcs_tag,
    )
    choices = plan_gate_choice_ids(tier)
    plan_name = plan_file.name
    return {
        "schema_version": 1,
        "kind": "plan" if tier == "tale" else "epic_plan",
        "request_id": session_id,
        "producer": {
            key: value
            for key, value in {
                "agent_name": agent_name,
                "agent_model": agent_model,
                "agent_llm_provider": agent_llm_provider,
                "agent_runtime": agent_runtime,
                "agent_vcs_tag": agent_vcs_tag,
                "artifacts_dir": os.environ.get("SASE_ARTIFACTS_DIR"),
            }.items()
            if value
        },
        "continuation_mode": PLAN_CONTINUATION_MODE,
        "payload": {
            "authored_tier": tier,
            "original_plan_file": str(plan_file),
            "plan_resource": PLAN_RESOURCE_PATH,
            "session_id": session_id,
            "timestamp": time.time(),
        },
        "presentation": {
            "notes": [
                (
                    "Epic ready for review: "
                    if tier == "epic"
                    else "Plan ready for review: "
                )
                + plan_name
            ],
            "tags": ["epic" if tier == "epic" else "plan"],
            "files": [PLAN_RESOURCE_PATH],
            "action_data": action_data,
        },
        "choices": [_plan_gate_choice(choice) for choice in choices],
        "operations": [
            {
                "id": PLAN_EDIT_OPERATION_ID,
                "kind": "edit_file",
                "target": PLAN_RESOURCE_PATH,
            }
        ],
        "resources": [
            {
                "path": PLAN_RESOURCE_PATH,
                "role": "editable",
                "source": str(plan_file),
            },
            *[
                {
                    "path": f"commands/{choice}",
                    "role": "command",
                    "content": plan_gate_command_script(choice),
                }
                for choice in choices
            ],
        ],
        "auto": {
            "enabled": auto_enabled,
            "argument": auto_argument,
        },
    }


def plan_gate_choice_ids(tier: PlanGateTier) -> tuple[str, ...]:
    """Return the closed choice set for a newly-authored plan gate."""
    if tier == "epic":
        return ("epic", "reject", "feedback")
    return ("approve", "run", "tale", "commit", "reject", "feedback")


def validate_plan_auto_argument(tier: PlanGateTier, argument: str | None) -> None:
    """Reject unknown or tier-changing plan auto aliases before handoff."""
    allowed = (
        {None, "", "epic", "epic_plan"}
        if tier == "epic"
        else {None, "", "plan", "tale"}
    )
    if argument not in allowed:
        raise GateError(
            "invalid_auto_argument",
            "auto.argument",
            f"%auto:{argument} conflicts with the authored {tier} plan tier",
        )


def plan_gate_command_script(choice: str) -> str:
    """Return the hashed adapter-owned command wrapper for *choice*."""
    return (
        f"#!{sys.executable}\n"
        "from sase.plan_gate import execute_plan_gate_command\n"
        f"raise SystemExit(execute_plan_gate_command({choice!r}))\n"
    )


@gate_command_entrypoint
def execute_plan_gate_command(choice: str) -> int:
    """Entry point used by the command resources inside plan gate bundles."""
    try:
        raw_input = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"invalid command input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(raw_input, dict):
        print("plan command input must be an object", file=sys.stderr)
        return 2

    try:
        envelope = json.loads((Path.cwd() / "request.json").read_text(encoding="utf-8"))
        if not isinstance(envelope, dict):
            raise ValueError("request envelope is not an object")
        kind = envelope.get("kind")
        tier: PlanGateTier = "epic" if kind == "epic_plan" else "tale"
        allowed = plan_gate_choice_ids(tier)
        if choice not in allowed:
            raise ValueError(f"choice {choice!r} is not valid for a {tier} plan")

        if choice not in {"reject", "feedback"}:
            from sase.plan_approval_actions import require_plan_approval_validation

            require_plan_approval_validation(Path.cwd() / PLAN_RESOURCE_PATH, tier)

        feedback = _optional_text(raw_input.get("feedback"))
        from sase.plan_approval_actions import plan_response_json

        result, _message = plan_response_json(
            choice,
            feedback=feedback,
            commit_plan=_optional_bool(raw_input.get("commit_plan")),
            run_coder=_optional_bool(raw_input.get("run_coder")),
            coder_prompt=_optional_text(raw_input.get("coder_prompt")),
            coder_model=_optional_text(raw_input.get("coder_model")),
        )
        if choice == "epic":
            mode = raw_input.get("epic_launch_mode", "detached")
            if mode not in {"detached", "foreground", "skip"}:
                raise ValueError(f"unsupported epic launch mode: {mode}")
            context = plan_context_from_envelope(Path.cwd(), envelope)
            from sase.plan_approval_actions import can_claim_epic_launch

            if can_claim_epic_launch(context, mode=mode):
                result["epic_launch_owner"] = "host"
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(result, sort_keys=True))
    return 0


def plan_context_from_envelope(bundle_path: Path, envelope: Mapping[str, Any]) -> Any:
    """Build a host action context from a trusted neutral request envelope."""
    from sase.plan_approval_actions import PlanApprovalActionContext

    presentation = envelope.get("presentation")
    action_data: dict[str, str] = {}
    if isinstance(presentation, Mapping):
        raw_action_data = presentation.get("action_data")
        if isinstance(raw_action_data, Mapping):
            action_data = {
                str(key): str(value)
                for key, value in raw_action_data.items()
                if isinstance(key, str) and isinstance(value, str)
            }
    action_data.update(
        {
            "response_dir": str(bundle_path),
            "bundle_path": str(bundle_path),
            "request_id": str(envelope.get("request_id") or bundle_path.name),
            "request_kind": str(envelope.get("kind") or "plan"),
        }
    )
    notification_id = envelope.get("notification_id")
    return PlanApprovalActionContext(
        id=(
            notification_id
            if isinstance(notification_id, str) and notification_id
            else str(envelope.get("request_id") or bundle_path.name)
        ),
        host_files=(str(bundle_path / PLAN_RESOURCE_PATH),),
        host_action_data=action_data,
    )


def translate_plan_gate_response(
    bundle_path: Path, response: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the legacy runner result embedded in a neutral response."""
    result = response.get("result")
    if not isinstance(result, Mapping):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "plan gate response has no result object",
        )
    return dict(result)


def execute_plan_gate_auto_choice(
    bundle_path: Path,
    argument: str | None,
    *,
    source: str = "auto_resolution",
) -> dict[str, Any]:
    """Resolve a previously-manual plan gate using its adapter auto policy."""
    from sase.notification_gates.executor import execute_gate_choice
    from sase.notification_gates.hashing import load_and_verify_bundle
    from sase.notification_gates.models import GateChoice

    envelope, adapter = load_and_verify_bundle(bundle_path)
    raw_choices = envelope.get("choices")
    if not isinstance(raw_choices, list):
        raise GateError("invalid_request", "choices", "choices are missing")
    choices = tuple(
        GateChoice.from_mapping(raw_choice, index)
        for index, raw_choice in enumerate(raw_choices)
    )
    choice = adapter.resolve_auto_choice(choices, argument)
    input_data = (
        {"epic_launch_mode": "detached"} if envelope.get("kind") == "epic_plan" else {}
    )
    return execute_gate_choice(
        bundle_path,
        choice.id,
        input_data,
        source=source,
    ).response


def _plan_action_data(
    *,
    session_id: str,
    agent_name: str | None,
    agent_model: str | None,
    agent_llm_provider: str | None,
    agent_runtime: str | None,
    agent_vcs_tag: str | None,
) -> dict[str, str]:
    values = {
        "session_id": session_id,
        "project_dir": os.environ.get("CLAUDE_PROJECT_DIR"),
        "artifacts_dir": os.environ.get("SASE_ARTIFACTS_DIR"),
        "agent_cl_name": os.environ.get("SASE_AGENT_CL_NAME"),
        "agent_project_file": os.environ.get("SASE_AGENT_PROJECT_FILE"),
        "agent_timestamp": os.environ.get("SASE_AGENT_TIMESTAMP"),
        "agent_root_timestamp": os.environ.get("SASE_AGENT_ROOT_TIMESTAMP"),
        "agent_name": agent_name,
        "model": agent_model,
        "llm_provider": agent_llm_provider,
        "runtime": agent_runtime,
        "agent_vcs_tag": agent_vcs_tag,
    }
    return {key: value for key, value in values.items() if value}


def _plan_gate_choice(choice: str) -> dict[str, Any]:
    input_schema = _plan_input_schema(choice)
    return {
        "id": choice,
        "label": _choice_label(choice),
        "command": {"argv": [f"commands/{choice}"]},
        "input_schema": input_schema,
        "result_schema": _plan_result_schema(choice),
    }


def _plan_input_schema(choice: str) -> dict[str, Any]:
    if choice == "feedback":
        return {
            "type": "object",
            "required": ["feedback"],
            "properties": {"feedback": {"type": "string", "minLength": 1}},
            "additionalProperties": False,
        }
    properties: dict[str, Any] = {}
    if choice in {"approve", "run", "tale"}:
        properties.update(
            {
                "coder_prompt": {"type": "string"},
                "coder_model": {"type": "string"},
            }
        )
    if choice == "approve":
        properties.update(
            {
                "commit_plan": {"type": "boolean"},
                "run_coder": {"type": "boolean"},
            }
        )
    if choice == "epic":
        properties["epic_launch_mode"] = {"enum": ["detached", "foreground", "skip"]}
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }


def _plan_result_schema(choice: str) -> dict[str, Any]:
    if choice in {"reject", "feedback"}:
        properties: dict[str, Any] = {"action": {"const": "reject"}}
        required = ["action"]
        if choice == "feedback":
            properties["feedback"] = {"type": "string", "minLength": 1}
            required.append("feedback")
        else:
            properties["feedback"] = {"type": "string"}
        return {
            "type": "object",
            "required": required,
            "properties": properties,
            "additionalProperties": False,
        }
    action = "epic" if choice == "epic" else "approve"
    return {
        "type": "object",
        "required": ["action", "commit_plan", "run_coder"],
        "properties": {
            "action": {"const": action},
            "commit_plan": {"type": "boolean"},
            "run_coder": {"type": "boolean"},
            "coder_prompt": {"type": "string"},
            "coder_model": {"type": "string"},
            "epic_launch_owner": {"const": "host"},
        },
        "additionalProperties": False,
    }


def _choice_label(choice: str) -> str:
    return "Send Feedback" if choice == "feedback" else choice.title()


def _optional_text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


__all__ = [
    "PLAN_CONTINUATION_MODE",
    "PLAN_EDIT_OPERATION_ID",
    "PLAN_RESOURCE_PATH",
    "create_plan_approval_gate",
    "execute_plan_gate_auto_choice",
    "execute_plan_gate_command",
    "plan_context_from_envelope",
    "plan_gate_choice_ids",
    "plan_gate_command_script",
    "validate_plan_auto_argument",
    "translate_plan_gate_response",
]
