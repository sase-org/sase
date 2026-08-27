"""Tiered command-backed plan approval gates.

This module is the public entry point for plan gate specs; command
execution, tier metadata, and response translation live in the sibling
``_plan_gate_*`` modules and are re-exported here.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, get_args

from sase._plan_approval_protocol import EpicLaunchMode
from sase.env_contracts import provider_project_dir_from_env
from sase.notification_gates.models import GateError

from ._plan_gate_command import execute_plan_gate_command, plan_gate_command_script
from ._plan_gate_envelope import (
    original_plan_file_for_resource,
    original_plan_file_from_bundle,
    plan_context_from_envelope,
    translate_plan_gate_response,
)
from ._plan_gate_metadata import (
    plan_gate_edit_operation,
    plan_gate_option_icon,
    plan_gate_option_ids,
    plan_gate_option_label,
    plan_gate_query,
    validate_plan_auto_argument,
)
from ._plan_gate_shared import (
    PLAN_APPROVE_OPTION_ID,
    PLAN_COMMIT_OPTION_ID,
    PLAN_CONTINUATION_MODE,
    PLAN_EDIT_OPERATION_ID,
    PLAN_FEEDBACK_OPTION_ID,
    PLAN_REJECT_OPTION_ID,
    PLAN_RESOURCE_PATH,
    PlanGateTier,
    TALE_PLAN_SUBMIT_GROUP,
)

if TYPE_CHECKING:
    from sase.sdd.plan_validate import PlanValidationResult


def build_plan_approval_gate_spec(
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
) -> dict[str, Any]:
    """Return the validated neutral plan gate request before creation."""
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

    validation = require_plan_approval_validation(plan_path, typed_tier)
    return _build_plan_gate_spec(
        plan_path,
        session_id,
        tier=typed_tier,
        validation=validation,
        auto_enabled=auto_enabled,
        auto_argument=auto_argument,
        agent_name=agent_name,
        agent_model=agent_model,
        agent_llm_provider=agent_llm_provider,
        agent_runtime=agent_runtime,
        agent_vcs_tag=agent_vcs_tag,
    )


def _build_plan_gate_spec(
    plan_file: Path,
    session_id: str,
    *,
    tier: PlanGateTier,
    validation: PlanValidationResult,
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
        original_plan_file=str(plan_file),
        session_id=session_id,
        agent_name=agent_name,
        agent_model=agent_model,
        agent_llm_provider=agent_llm_provider,
        agent_runtime=agent_runtime,
        agent_vcs_tag=agent_vcs_tag,
    )
    from sase.sdd.plan_summary import encode_plan_counts, plan_counts_summary

    counts_summary = plan_counts_summary(validation, tier=tier)
    if counts_summary is not None:
        action_data.update(encode_plan_counts(counts_summary))
    option_ids = plan_gate_option_ids(tier)
    plan_name = plan_file.name
    return {
        "schema_version": 3,
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
                    else "Tale ready for review: "
                )
                + plan_name
            ],
            "tags": ["epic" if tier == "epic" else "plan"],
            "files": [PLAN_RESOURCE_PATH],
            "action_data": action_data,
        },
        "query": plan_gate_query(tier),
        "primary_branch": (
            [PLAN_APPROVE_OPTION_ID]
            if tier == "epic"
            else [PLAN_APPROVE_OPTION_ID, PLAN_COMMIT_OPTION_ID]
        ),
        "options": [
            _plan_gate_option(option_id, tier=tier) for option_id in option_ids
        ],
        "groups": ([TALE_PLAN_SUBMIT_GROUP.to_dict()] if tier == "tale" else []),
        "operations": [plan_gate_edit_operation(tier)],
        "resources": [
            {
                "path": PLAN_RESOURCE_PATH,
                "role": "editable",
                "source": str(plan_file),
            },
            *[
                {
                    "path": f"commands/{option_id}",
                    "role": "command",
                    "content": plan_gate_command_script(option_id),
                }
                for option_id in option_ids
            ],
        ],
        "auto": {
            "enabled": auto_enabled,
            "argument": auto_argument,
        },
    }


def _plan_action_data(
    *,
    original_plan_file: str,
    session_id: str,
    agent_name: str | None,
    agent_model: str | None,
    agent_llm_provider: str | None,
    agent_runtime: str | None,
    agent_vcs_tag: str | None,
) -> dict[str, str]:
    values = {
        "original_plan_file": original_plan_file,
        "session_id": session_id,
        "project_dir": provider_project_dir_from_env(),
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


def _plan_gate_option(option_id: str, *, tier: PlanGateTier) -> dict[str, Any]:
    return {
        "id": option_id,
        "label": plan_gate_option_label(option_id, tier=tier),
        "icon": plan_gate_option_icon(option_id, tier=tier),
        "default_selected": True,
        "command": {"argv": [f"commands/{option_id}"]},
        "input_schema": _plan_input_schema(option_id, tier=tier),
        "result_schema": _plan_result_schema(option_id, tier=tier),
        "feedback": (
            "required" if option_id == PLAN_FEEDBACK_OPTION_ID else "disabled"
        ),
    }


def _plan_input_schema(option_id: str, *, tier: PlanGateTier) -> dict[str, Any]:
    if option_id == PLAN_FEEDBACK_OPTION_ID:
        return {
            "type": "object",
            "required": ["feedback"],
            "properties": {"feedback": {"type": "string", "minLength": 1}},
            "additionalProperties": False,
        }
    properties: dict[str, Any] = {}
    if tier == "tale" and option_id in {
        PLAN_APPROVE_OPTION_ID,
        PLAN_COMMIT_OPTION_ID,
    }:
        # Every selected option receives the same input. Both AND-group members
        # therefore admit the coder fields even though only approve consumes them.
        properties.update(
            {
                "coder_prompt": {"type": "string"},
                "coder_model": {"type": "string"},
            }
        )
    if tier == "epic" and option_id == PLAN_APPROVE_OPTION_ID:
        # Mirror EpicLaunchMode exactly; a schema narrower than the domain type
        # rejects submissions the responder and prepare_epic_launch both accept.
        properties["epic_launch_mode"] = {"enum": list(get_args(EpicLaunchMode))}
    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }


def _plan_result_schema(option_id: str, *, tier: PlanGateTier) -> dict[str, Any]:
    if option_id in {PLAN_REJECT_OPTION_ID, PLAN_FEEDBACK_OPTION_ID}:
        properties: dict[str, Any] = {"action": {"const": "reject"}}
        required = ["action"]
        if option_id == PLAN_FEEDBACK_OPTION_ID:
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
    action = "epic" if tier == "epic" else "approve"
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


__all__ = [
    "PLAN_APPROVE_OPTION_ID",
    "PLAN_COMMIT_OPTION_ID",
    "PLAN_CONTINUATION_MODE",
    "PLAN_EDIT_OPERATION_ID",
    "PLAN_FEEDBACK_OPTION_ID",
    "PLAN_REJECT_OPTION_ID",
    "PLAN_RESOURCE_PATH",
    "build_plan_approval_gate_spec",
    "execute_plan_gate_command",
    "original_plan_file_for_resource",
    "original_plan_file_from_bundle",
    "plan_context_from_envelope",
    "plan_gate_command_script",
    "plan_gate_edit_operation",
    "plan_gate_option_icon",
    "plan_gate_option_label",
    "plan_gate_option_ids",
    "plan_gate_query",
    "validate_plan_auto_argument",
    "translate_plan_gate_response",
]
