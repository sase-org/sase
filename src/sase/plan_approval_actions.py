"""Shared plan approval response orchestration and side effects.

The public API remains in this module while protocol, artifact-resolution,
epic-launch, response-execution, and terminal side-effect details live in
focused implementation modules.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase._plan_approval_artifacts import (
    durable_plan_file_for_context as durable_plan_file_for_context,
)
from sase._plan_approval_artifacts import (
    resolve_plan_agent_artifacts_dir as resolve_plan_agent_artifacts_dir,
)
from sase._plan_approval_epic import (
    can_claim_epic_launch as can_claim_epic_launch,
)
from sase._plan_approval_epic import epic_launch_project as _epic_launch_project
from sase._plan_approval_epic import prepare_epic_launch as prepare_epic_launch
from sase._plan_approval_protocol import (
    PLAN_APPROVAL_ACTIONS as PLAN_APPROVAL_ACTIONS,
)
from sase.core.agent_tribe import canonicalize_agent_tribe_metadata
from sase._plan_approval_protocol import PLAN_APPROVAL_KINDS as PLAN_APPROVAL_KINDS
from sase._plan_approval_protocol import EpicLaunchMode as EpicLaunchMode
from sase._plan_approval_protocol import (
    PlanApprovalActionContext as PlanApprovalActionContext,
)
from sase._plan_approval_protocol import (
    PlanApprovalActionError as PlanApprovalActionError,
)
from sase._plan_approval_protocol import (
    PlanApprovalActionResult as PlanApprovalActionResult,
)
from sase._plan_approval_protocol import (
    PlanApprovalValidationError as PlanApprovalValidationError,
)
from sase._plan_approval_protocol import persisted_plan_action as persisted_plan_action
from sase._plan_approval_protocol import plan_response_json as plan_response_json
from sase._plan_approval_protocol import (
    plan_response_json_for_selection as plan_response_json_for_selection,
)
from sase._plan_approval_protocol import (
    require_plan_approval_validation as require_plan_approval_validation,
)
from sase._plan_approval_protocol import (
    resolve_plan_approval_choice as _resolve_plan_approval_choice,
)
from sase._plan_approval_response import (
    epic_launch_submission_ids as _epic_launch_submission_ids,
)
from sase._plan_approval_response import (
    execute_neutral_plan_approval_response as _execute_neutral_plan_approval_response,
)
from sase._plan_approval_response import (
    parse_plan_approval_capacity as _parse_plan_approval_capacity,
)
from sase._plan_approval_response import (
    parse_plan_approval_wait as _parse_plan_approval_wait,
)
from sase._plan_approval_response import write_json_once as _write_json_once
from sase._plan_approval_side_effects import (
    apply_plan_post_terminal_side_effects as apply_plan_post_terminal_side_effects,
)
from sase._plan_approval_side_effects import (
    archive_plan_for_approval as _archive_plan_for_approval,
)
from sase._plan_approval_side_effects import (
    dismiss_notification_best_effort as dismiss_notification_best_effort,
)
from sase._plan_approval_side_effects import (
    preflight_plan_archive_credential as preflight_plan_archive_credential,
)
from sase._plan_approval_side_effects import (
    sync_reviewed_plan_to_durable_best_effort as _sync_reviewed_plan_to_durable_best_effort,
)
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.plan_approval_choices import (
    plan_approval_response_message_for_selection as plan_approval_response_message_for_selection,
)
from sase.plan_approval_choices import (
    plan_approval_selection_for_choice as plan_approval_selection_for_choice,
)

if TYPE_CHECKING:
    from sase.bead.epic_launch import EpicLaunchOrigin, EpicLaunchSubmission
    from sase.xprompt.directive_edit import PromptWaitDirective

HOST_PLAN_ARCHIVE_PROTOCOL = "host_v2"


def execute_plan_approval_response(
    notification: PlanApprovalActionContext,
    choice: str | None,
    *,
    feedback: str | None = None,
    commit_plan: bool | None = None,
    run_coder: bool | None = None,
    coder_prompt: str | None = None,
    coder_model: str | None = None,
    wait: str | None = None,
    capacity: int | None = None,
    epic_launch_mode: EpicLaunchMode = "launch",
    epic_launch_origin: EpicLaunchOrigin = "api",
    option_inputs: Mapping[str, Mapping[str, Any]] | None = None,
) -> PlanApprovalActionResult:
    """Resolve a neutral plan gate, with legacy in-flight fallback."""
    wait_spec = _parse_plan_approval_wait(wait)
    capacity = _parse_plan_approval_capacity(capacity)
    request_kind = notification.host_action_data.get("request_kind")
    action = "EpicApproval" if request_kind == "epic_plan" else "PlanApproval"
    from sase.notification_gates.paths import resolve_action_bundle

    bundle = resolve_action_bundle(action, notification.host_action_data)
    if bundle is not None and not bundle.legacy:
        return _execute_neutral_plan_approval_response(
            notification,
            bundle.root,
            choice,
            feedback=feedback,
            commit_plan=commit_plan,
            run_coder=run_coder,
            coder_prompt=coder_prompt,
            coder_model=coder_model,
            wait=wait,
            wait_spec=wait_spec,
            capacity=capacity,
            epic_launch_mode=epic_launch_mode,
            epic_launch_origin=epic_launch_origin,
            option_inputs=option_inputs,
        )
    return _execute_legacy_plan_approval_response(
        notification,
        choice,
        feedback=feedback,
        commit_plan=commit_plan,
        run_coder=run_coder,
        coder_prompt=coder_prompt,
        coder_model=coder_model,
        wait_spec=wait_spec,
        capacity=capacity,
        epic_launch_mode=epic_launch_mode,
        epic_launch_origin=epic_launch_origin,
    )


def _execute_legacy_plan_approval_response(
    notification: PlanApprovalActionContext,
    choice: str | None,
    *,
    feedback: str | None,
    commit_plan: bool | None,
    run_coder: bool | None,
    coder_prompt: str | None,
    coder_model: str | None,
    wait_spec: PromptWaitDirective | None,
    capacity: int | None,
    epic_launch_mode: EpicLaunchMode,
    epic_launch_origin: EpicLaunchOrigin,
) -> PlanApprovalActionResult:
    """Write the runner response for an in-flight legacy PlanApproval."""
    raw_response_dir = notification.host_action_data.get("response_dir")
    if not raw_response_dir:
        raise PlanApprovalActionError(
            "invalid_request", "response_dir", "response_dir is missing"
        )

    response_dir = Path(raw_response_dir).expanduser()
    if not response_dir.is_dir():
        raise PlanApprovalActionError(
            "invalid_request", "response_dir", "response_dir is missing"
        )
    if not (response_dir / "plan_request.json").is_file():
        raise PlanApprovalActionError(
            "conflict_already_handled",
            notification.id,
            "plan request was already consumed",
        )
    if not notification.host_files:
        raise PlanApprovalActionError(
            "invalid_request", "plan_file", "plan file is missing"
        )

    choice = _resolve_plan_approval_choice(notification.host_files[0], choice)
    response_json, message = plan_response_json(
        choice,
        feedback=feedback,
        commit_plan=commit_plan,
        run_coder=run_coder,
        coder_prompt=coder_prompt,
        coder_model=coder_model,
        wait_spec=wait_spec,
        capacity=capacity,
    )
    response_path = response_dir / "plan_response.json"
    epic_launch_project: str | None = None
    if choice == "epic":
        can_claim_epic_launch(
            notification,
            mode=epic_launch_mode,
            wait_spec=wait_spec,
            capacity=capacity,
        )
        if epic_launch_mode != "skip":
            epic_launch_project = _epic_launch_project(notification)
        # Transitional compatibility: pre-upgrade agents launch the epic
        # themselves unless the response explicitly assigns ownership here.
        response_json["epic_launch_owner"] = "host"
    prepare_plan_terminal_response(notification, choice, response_json)
    _write_json_once(response_path, response_json, notification.id)
    apply_plan_post_terminal_side_effects(
        notification,
        choice,
        source="plan_response",
    )
    epic_launch_monitor_id: str | None = None
    epic_launch_task_id: str | None = None
    if choice == "epic" and epic_launch_mode != "skip":
        launch = prepare_epic_launch(
            notification,
            Path(notification.host_files[0]),
            mode=epic_launch_mode,
            response_dir=response_dir,
            resolved_project=epic_launch_project,
            origin=epic_launch_origin,
            wait_spec=wait_spec,
            capacity=capacity,
        )
        epic_launch_monitor_id, epic_launch_task_id = _epic_launch_submission_ids(
            launch
        )
    return PlanApprovalActionResult(
        notification_id=notification.id,
        response_file="plan_response.json",
        response_path=response_path,
        response_json=response_json,
        message=message,
        epic_launch_monitor_id=epic_launch_monitor_id,
        epic_launch_task_id=epic_launch_task_id,
    )


def run_plan_side_effects(
    notification: PlanApprovalActionContext,
    choice: str,
    response_path: Path,
    response_json: dict[str, Any],
    *,
    response_container: dict[str, Any] | None = None,
    source: str = "plan_response",
) -> None:
    prepare_plan_terminal_response(notification, choice, response_json)
    if response_path.exists():
        try:
            if response_container is not None:
                from sase.notification_gates.durability import atomic_write_json

                atomic_write_json(response_path, response_container)
            else:
                response_path.write_text(
                    json.dumps(response_json, indent=2) + "\n",
                    encoding="utf-8",
                )
        except OSError:
            pass
    apply_plan_post_terminal_side_effects(notification, choice, source=source)


def prepare_plan_terminal_response(
    notification: PlanApprovalActionContext,
    choice: str,
    response_json: dict[str, Any],
) -> None:
    """Prepare runner-visible plan response fields before terminal publication."""
    del choice
    persisted_action = _persist_plan_approved_metadata(notification, response_json)
    if persisted_action is None:
        return

    _sync_reviewed_plan_to_durable_best_effort(notification)

    if _response_requires_host_plan_archive(response_json, persisted_action):
        archive = _archive_plan_for_approval(
            notification,
            persisted_action,
            required=True,
        )
        saved_path = _archive_saved_plan_path(archive)
        if not saved_path:
            raise PlanApprovalActionError(
                "plan_archive_failed",
                "saved_plan_path",
                "approved plan archive did not return a saved path",
            )
        _apply_host_plan_archive_fields(response_json, archive)
        _project_plan_committed(notification, persisted_action)
        return

    if response_json.get("action") in {"approve", "epic"}:
        response_json["plan_archive_owner"] = "none"
        response_json["plan_archive_state"] = "not_requested"


def _response_requires_host_plan_archive(
    response_json: dict[str, Any],
    persisted_action: str,
) -> bool:
    return (
        persisted_action in {"commit", "tale"}
        and response_json.get("action") == "approve"
        and response_json.get("commit_plan") is True
    )


def _archive_saved_plan_path(archive: object | None) -> str | None:
    if isinstance(archive, str) and archive.strip():
        return archive
    return None


def _apply_host_plan_archive_fields(
    response_json: dict[str, Any],
    archive: object,
) -> None:
    """Attach the host-owned archive fields before terminal publication."""
    saved_path = _archive_saved_plan_path(archive)
    response_json["plan_archive_owner"] = "host"
    response_json["plan_archive_state"] = "archived"
    if saved_path is not None:
        response_json["saved_plan_path"] = saved_path
    archive_ref = getattr(archive, "plan_archive_ref", None)
    if isinstance(archive_ref, str) and archive_ref.strip():
        response_json["plan_archive_protocol"] = HOST_PLAN_ARCHIVE_PROTOCOL
        response_json["plan_archive_ref"] = archive_ref.strip()


def _persist_plan_approved_metadata(
    notification: PlanApprovalActionContext,
    response_json: dict[str, Any],
) -> str | None:
    action = persisted_plan_action(response_json)
    if action is None:
        return None
    if action == "commit":
        # PLAN COMMITTED waits for archive success in `_project_plan_committed`.
        return action
    _write_plan_action_metadata(notification, action)
    return action


def _write_plan_action_metadata(
    notification: PlanApprovalActionContext,
    action: str,
    *,
    plan_committed: bool | None = None,
) -> None:
    artifacts_dir = resolve_plan_agent_artifacts_dir(notification.host_action_data)
    if artifacts_dir:
        meta_path = Path(artifacts_dir) / "agent_meta.json"
    else:
        raw_response_dir = notification.host_action_data.get("response_dir")
        if not raw_response_dir:
            return
        meta_path = Path(raw_response_dir).expanduser().parent / "agent_meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            meta = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        meta = {}

    meta["plan_approved"] = True
    meta["plan_action"] = action
    if plan_committed is not None:
        meta["plan_committed"] = plan_committed
    canonicalize_agent_tribe_metadata(meta)
    try:
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        update_agent_artifact_index_for_marker_mutation(meta_path.parent)
    except OSError:
        pass


def _project_plan_committed(
    notification: PlanApprovalActionContext,
    persisted_action: str,
) -> None:
    bundle = notification.host_action_data.get(
        "bundle_path"
    ) or notification.host_action_data.get("response_dir")
    if bundle:
        from sase.notification_gates.approval_projection import project_plan_committed

        project_plan_committed(Path(bundle), action=persisted_action)
    if persisted_action == "commit":
        _write_plan_action_metadata(notification, "commit", plan_committed=True)
