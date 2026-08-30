"""Translation between neutral plan gate envelopes and host action contexts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.notification_gates.models import GateError

from ._plan_gate_shared import (
    PLAN_APPROVE_OPTION_ID,
    PLAN_RESOURCE_PATH,
    plan_gate_optional_text,
)

if TYPE_CHECKING:
    from sase.xprompt.directive_edit import PromptWaitDirective


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
            coder_prompt=plan_gate_optional_text(approve_result.get("coder_prompt")),
            coder_model=plan_gate_optional_text(approve_result.get("coder_model")),
            epic_launch_owner=plan_gate_optional_text(
                primary_result.get("epic_launch_owner")
            ),
            wait_spec=_wait_spec_from_approve_result(approve_result),
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
    plan_archive_protocol = primary_result.get("plan_archive_protocol")
    if isinstance(plan_archive_protocol, str) and plan_archive_protocol:
        translated["plan_archive_protocol"] = plan_archive_protocol
    plan_archive_ref = primary_result.get("plan_archive_ref")
    if isinstance(plan_archive_ref, str) and plan_archive_ref:
        translated["plan_archive_ref"] = plan_archive_ref
    wait_agents = approve_result.get("wait_agents")
    if isinstance(wait_agents, list):
        translated["wait_agents"] = wait_agents
    wait_beads = approve_result.get("wait_beads")
    if isinstance(wait_beads, list):
        translated["wait_beads"] = wait_beads
    return translated


def _wait_spec_from_approve_result(
    result: Mapping[str, Any],
) -> PromptWaitDirective | None:
    """Rebuild the parsed wait spec from the approve option's command result."""
    from sase.wait_spec import wait_spec_from_name_lists

    return wait_spec_from_name_lists(
        result.get("wait_agents"),
        result.get("wait_beads"),
    )


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
