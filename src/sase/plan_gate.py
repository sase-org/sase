"""Tiered command-backed plan approval gates."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Literal, cast, get_args

from sase._plan_approval_protocol import EpicLaunchMode
from sase.env_contracts import provider_project_dir_from_env
from sase.notification_gates.entrypoints import gate_command_entrypoint
from sase.notification_gates.models import GateError, GateGroup

if TYPE_CHECKING:
    from sase.sdd.plan_validate import PlanValidationResult

PLAN_EDIT_OPERATION_ID = "edit_plan"
PLAN_RESOURCE_PATH = "plan.md"
PLAN_CONTINUATION_MODE = "agent_plan"
PLAN_APPROVE_OPTION_ID = "approve"
PLAN_COMMIT_OPTION_ID = "commit"
PLAN_REJECT_OPTION_ID = "reject"
PLAN_FEEDBACK_OPTION_ID = "feedback"

TALE_PLAN_SUBMIT_GROUP = GateGroup(
    options=(PLAN_APPROVE_OPTION_ID, PLAN_COMMIT_OPTION_ID),
    label="Tale",
    icon="✅",
)

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

    validation = require_plan_approval_validation(plan_path, typed_tier)
    from sase.notification_gates.service import create_gate

    return create_gate(
        _build_plan_gate_spec(
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


def plan_gate_edit_operation(tier: PlanGateTier) -> dict[str, Any]:
    """Return the declared edit action registered for a plan tier.

    Both tiers declare it, and both point at ``edit_target: "origin"``: the
    durable file under ``~/.sase/plans/`` that ``sase plan propose`` wrote, not
    the bundle copy that approval overwrites it from.
    """
    return {
        "id": PLAN_EDIT_OPERATION_ID,
        "kind": "edit_file",
        "target": PLAN_RESOURCE_PATH,
        "edit_target": "origin",
        "label": "Edit epic plan" if tier == "epic" else "Edit plan",
        "icon": "✏️",
        "key": "e",
        "description": "Accepted only when `sase plan validate` passes.",
    }


def plan_gate_query(tier: PlanGateTier) -> str:
    """Return the exact option query registered for a plan tier."""
    if tier == "epic":
        return "approve OR reject OR feedback"
    return "(approve AND commit) OR reject OR feedback"


def plan_gate_option_ids(tier: PlanGateTier) -> tuple[str, ...]:
    """Return the query-ordered option ids registered for a plan tier."""
    if tier == "epic":
        return (
            PLAN_APPROVE_OPTION_ID,
            PLAN_REJECT_OPTION_ID,
            PLAN_FEEDBACK_OPTION_ID,
        )
    return (
        PLAN_APPROVE_OPTION_ID,
        PLAN_COMMIT_OPTION_ID,
        PLAN_REJECT_OPTION_ID,
        PLAN_FEEDBACK_OPTION_ID,
    )


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


def plan_gate_command_script(option_id: str) -> str:
    """Return the hashed adapter-owned command wrapper for *option_id*."""
    return (
        f"#!{sys.executable}\n"
        "from sase.plan_gate import execute_plan_gate_command\n"
        f"raise SystemExit(execute_plan_gate_command({option_id!r}))\n"
    )


@gate_command_entrypoint
def execute_plan_gate_command(option_id: str) -> int:
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
        if option_id not in plan_gate_option_ids(tier):
            raise ValueError(f"option {option_id!r} is not valid for a {tier} plan")

        if option_id not in {PLAN_REJECT_OPTION_ID, PLAN_FEEDBACK_OPTION_ID}:
            from sase.plan_approval_actions import require_plan_approval_validation

            require_plan_approval_validation(Path.cwd() / PLAN_RESOURCE_PATH, tier)

        feedback = _optional_text(raw_input.get("feedback"))
        from sase.plan_approval_actions import plan_response_json

        protocol_choice = (
            "epic"
            if tier == "epic" and option_id == PLAN_APPROVE_OPTION_ID
            else option_id
        )
        result, _message = plan_response_json(
            protocol_choice,
            feedback=feedback,
            commit_plan=None,
            run_coder=None,
            coder_prompt=_optional_text(raw_input.get("coder_prompt")),
            coder_model=_optional_text(raw_input.get("coder_model")),
        )
        if protocol_choice == "epic":
            mode = raw_input.get("epic_launch_mode", "launch")
            if mode not in {"launch", "detached", "skip"}:
                raise ValueError(f"unsupported epic launch mode: {mode}")
            # Transitional compatibility for pre-upgrade agents, which launch
            # the epic themselves unless the host owner is explicit.
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
    original_plan_file = _original_plan_file_from_envelope(envelope)
    if original_plan_file is not None:
        action_data["original_plan_file"] = str(original_plan_file)
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
    """Derive the runner protocol from a v2 selected-option response."""
    raw_selected = response.get("selected_option_ids")
    if (
        not isinstance(raw_selected, list)
        or not raw_selected
        or not all(isinstance(option_id, str) for option_id in raw_selected)
    ):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "plan gate response has no selected options",
        )
    selected = tuple(raw_selected)
    option_results = response.get("option_results")
    if not isinstance(option_results, list):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "plan gate response has no option results",
        )
    results_by_id = {
        entry.get("id"): entry.get("result")
        for entry in option_results
        if isinstance(entry, Mapping) and isinstance(entry.get("id"), str)
    }
    primary_result = results_by_id.get(selected[0])
    if not isinstance(primary_result, Mapping):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "plan gate response is missing its primary option result",
        )

    try:
        envelope = json.loads(
            (bundle_path / "request.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateError(
            "invalid_response",
            str(bundle_path / "request.json"),
            "plan gate request cannot be read",
        ) from exc
    if not isinstance(envelope, Mapping):
        raise GateError(
            "invalid_response",
            str(bundle_path / "request.json"),
            "plan gate request is not an object",
        )

    feedback = response.get("feedback")
    normalized_feedback = feedback if isinstance(feedback, str) and feedback else None
    approve_result = results_by_id.get(PLAN_APPROVE_OPTION_ID)
    approve_result = approve_result if isinstance(approve_result, Mapping) else {}
    from sase.plan_approval_actions import (
        PlanApprovalActionError,
        plan_response_json_for_selection,
    )

    try:
        translated, _message = plan_response_json_for_selection(
            selected,
            tier="epic" if envelope.get("kind") == "epic_plan" else "tale",
            feedback=normalized_feedback,
            coder_prompt=_optional_text(approve_result.get("coder_prompt")),
            coder_model=_optional_text(approve_result.get("coder_model")),
            epic_launch_owner=_optional_text(primary_result.get("epic_launch_owner")),
        )
    except PlanApprovalActionError as exc:
        raise GateError(exc.code, exc.target, str(exc)) from exc
    saved_plan_path = primary_result.get("saved_plan_path")
    if isinstance(saved_plan_path, str) and saved_plan_path:
        translated["saved_plan_path"] = saved_plan_path
    plan_archive_owner = primary_result.get("plan_archive_owner")
    if isinstance(plan_archive_owner, str) and plan_archive_owner:
        translated["plan_archive_owner"] = plan_archive_owner
    plan_archive_state = primary_result.get("plan_archive_state")
    if isinstance(plan_archive_state, str) and plan_archive_state:
        translated["plan_archive_state"] = plan_archive_state
    return translated


def execute_plan_gate_auto_choice(
    bundle_path: Path,
    argument: str | None,
    *,
    source: str = "auto_resolution",
) -> dict[str, Any]:
    """Resolve a previously-manual plan gate using its adapter auto policy."""
    from sase.notification_gates.executor import execute_gate_selection
    from sase.notification_gates.hashing import load_and_verify_bundle
    from sase.notification_gates.models import GateOption, GateSpec

    envelope, adapter = load_and_verify_bundle(bundle_path)
    raw_options = envelope.get("options")
    raw_branches = envelope.get("branches")
    raw_primary = envelope.get("primary_branch")
    if (
        not isinstance(raw_options, list)
        or not isinstance(raw_branches, list)
        or not isinstance(raw_primary, list)
    ):
        raise GateError(
            "invalid_request", str(bundle_path / "request.json"), "options are missing"
        )
    options = tuple(
        GateOption.from_mapping(raw_option, index)
        for index, raw_option in enumerate(raw_options)
    )
    branches = tuple(
        tuple(str(option_id) for option_id in branch)
        for branch in raw_branches
        if isinstance(branch, list)
    )
    primary_branch = tuple(str(option_id) for option_id in raw_primary)
    spec = cast(
        GateSpec,
        SimpleNamespace(
            options=options,
            branches=branches,
            primary_branch=primary_branch,
            payload=envelope.get("payload", {}),
        ),
    )
    selection = adapter.resolve_auto_selection(spec, argument)
    return execute_gate_selection(
        bundle_path,
        selection,
        adapter.automatic_input(spec),
        source=source,
    ).response


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


def _original_plan_file_from_envelope(
    envelope: Mapping[str, Any],
) -> Path | None:
    """Return the durable proposal path carried by a plan gate envelope."""
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        return None
    raw_path = payload.get("original_plan_file")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    return Path(raw_path).expanduser()


def original_plan_file_from_bundle(bundle_path: Path) -> Path | None:
    """Read the durable proposal path from a neutral plan gate bundle."""
    try:
        envelope = json.loads(
            (bundle_path.expanduser() / "request.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(envelope, Mapping) or envelope.get("kind") not in {
        "plan",
        "epic_plan",
    }:
        return None
    return _original_plan_file_from_envelope(envelope)


def original_plan_file_for_resource(resource_path: Path) -> Path | None:
    """Resolve a neutral plan resource back to its durable proposal path."""
    resource = resource_path.expanduser()
    bundle_path = resource.parent
    try:
        envelope = json.loads(
            (bundle_path / "request.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(envelope, Mapping) or envelope.get("kind") not in {
        "plan",
        "epic_plan",
    }:
        return None
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        return None
    plan_resource = payload.get("plan_resource")
    if not isinstance(plan_resource, str) or resource.name != plan_resource:
        return None
    return _original_plan_file_from_envelope(envelope)


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


def plan_gate_option_label(option_id: str, *, tier: PlanGateTier) -> str:
    """Return the tier-aware presentation label for a plan-gate option."""
    if option_id == PLAN_APPROVE_OPTION_ID:
        return "Epic" if tier == "epic" else "Launch coder agent"
    return {
        PLAN_COMMIT_OPTION_ID: "Commit plan file to the plans sidecar",
        PLAN_REJECT_OPTION_ID: "Reject",
        PLAN_FEEDBACK_OPTION_ID: "Send Feedback",
    }[option_id]


def plan_gate_option_icon(option_id: str, *, tier: PlanGateTier) -> str:
    """Return the tier-aware presentation icon for a plan-gate option."""
    if option_id == PLAN_APPROVE_OPTION_ID:
        return "✅" if tier == "epic" else "🚀"
    return {
        PLAN_COMMIT_OPTION_ID: "💾",
        PLAN_REJECT_OPTION_ID: "❌",
        PLAN_FEEDBACK_OPTION_ID: "💬",
    }[option_id]


def _optional_text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


__all__ = [
    "PLAN_APPROVE_OPTION_ID",
    "PLAN_COMMIT_OPTION_ID",
    "PLAN_CONTINUATION_MODE",
    "PLAN_EDIT_OPERATION_ID",
    "PLAN_FEEDBACK_OPTION_ID",
    "PLAN_REJECT_OPTION_ID",
    "PLAN_RESOURCE_PATH",
    "create_plan_approval_gate",
    "execute_plan_gate_auto_choice",
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
