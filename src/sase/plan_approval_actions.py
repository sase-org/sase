"""Shared plan approval response orchestration and side effects.

The public API remains in this module while protocol, artifact-resolution, and
epic-launch details live in focused implementation modules.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sase._plan_approval_artifacts import (
    durable_plan_file_for_context as durable_plan_file_for_context,
)
from sase._plan_approval_artifacts import (
    resolve_plan_agent_artifacts_dir as resolve_plan_agent_artifacts_dir,
)
from sase._plan_approval_epic import (
    can_claim_epic_launch as can_claim_epic_launch,
)
from sase._plan_approval_epic import epic_launch_cwd as _epic_launch_cwd
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
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.plan_approval_choices import (
    approval_choice_archives_plan,
    plan_approval_response_message_for_selection,
    plan_approval_selection_for_choice,
)

if TYPE_CHECKING:
    from sase.bead.epic_launch import EpicLaunchOrigin

_logger = logging.getLogger(__name__)


def execute_plan_approval_response(
    notification: PlanApprovalActionContext,
    choice: str | None,
    *,
    feedback: str | None = None,
    commit_plan: bool | None = None,
    run_coder: bool | None = None,
    coder_prompt: str | None = None,
    coder_model: str | None = None,
    epic_launch_mode: EpicLaunchMode = "detached",
    epic_launch_origin: EpicLaunchOrigin = "api",
) -> PlanApprovalActionResult:
    """Resolve a neutral plan gate, with legacy in-flight fallback."""
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
            epic_launch_mode=epic_launch_mode,
            epic_launch_origin=epic_launch_origin,
        )
    return _execute_legacy_plan_approval_response(
        notification,
        choice,
        feedback=feedback,
        commit_plan=commit_plan,
        run_coder=run_coder,
        coder_prompt=coder_prompt,
        coder_model=coder_model,
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
    )
    response_path = response_dir / "plan_response.json"
    epic_launch_cwd: Path | None = None
    if choice == "epic":
        can_claim_epic_launch(notification, mode=epic_launch_mode)
        if epic_launch_mode != "skip":
            epic_launch_cwd = _epic_launch_cwd(notification)
        # Transitional compatibility: pre-upgrade agents launch the epic
        # themselves unless the response explicitly assigns ownership here.
        response_json["epic_launch_owner"] = "host"
    _write_json_once(response_path, response_json, notification.id)

    run_plan_side_effects(notification, choice, response_path, response_json)
    epic_launch_task_id: str | None = None
    if choice == "epic" and epic_launch_mode != "skip":
        task = prepare_epic_launch(
            notification,
            Path(notification.host_files[0]),
            mode=epic_launch_mode,
            response_dir=response_dir,
            resolved_cwd=epic_launch_cwd,
            origin=epic_launch_origin,
        )
        epic_launch_task_id = task.task_id if task is not None else None
    return PlanApprovalActionResult(
        notification_id=notification.id,
        response_file="plan_response.json",
        response_path=response_path,
        response_json=response_json,
        message=message,
        epic_launch_task_id=epic_launch_task_id,
    )


def _execute_neutral_plan_approval_response(
    notification: PlanApprovalActionContext,
    bundle_path: Path,
    choice: str | None,
    *,
    feedback: str | None,
    commit_plan: bool | None,
    run_coder: bool | None,
    coder_prompt: str | None,
    coder_model: str | None,
    epic_launch_mode: EpicLaunchMode,
    epic_launch_origin: EpicLaunchOrigin,
) -> PlanApprovalActionResult:
    """Execute one selected option set through the shared gate executor."""
    if not notification.host_files:
        raise PlanApprovalActionError(
            "invalid_request", "plan_file", "plan file is missing"
        )
    resolved_choice = _resolve_plan_approval_choice(notification.host_files[0], choice)
    selection_choice = (
        "feedback"
        if resolved_choice == "reject" and feedback is not None
        else resolved_choice
    )
    from sase.notification_gates.hashing import load_and_verify_bundle
    from sase.notification_gates.models import GateError

    try:
        envelope, _adapter = load_and_verify_bundle(bundle_path)
    except GateError as exc:
        raise PlanApprovalActionError(exc.code, exc.target, str(exc)) from exc
    tier: Literal["tale", "epic"] = (
        "epic" if envelope.get("kind") == "epic_plan" else "tale"
    )
    try:
        selected_option_ids = plan_approval_selection_for_choice(
            selection_choice,
            tier=tier,
            commit_plan=commit_plan,
            run_coder=run_coder,
        )
    except (KeyError, ValueError) as exc:
        raise PlanApprovalActionError(
            "unsupported_action",
            selection_choice,
            f"unsupported {tier} plan action selection",
        ) from exc

    input_data: dict[str, Any] = {}
    if feedback is not None:
        input_data["feedback"] = feedback
    if "approve" in selected_option_ids and tier == "tale":
        if coder_prompt is not None:
            input_data["coder_prompt"] = coder_prompt
        if coder_model is not None:
            input_data["coder_model"] = coder_model
    if tier == "epic" and selected_option_ids == ("approve",):
        input_data["epic_launch_mode"] = epic_launch_mode

    from sase.notification_gates.executor import execute_gate_selection
    from sase.notification_gates.paths import RESPONSE_FILENAME

    try:
        execution = execute_gate_selection(
            bundle_path,
            selected_option_ids,
            input_data,
            feedback=feedback,
            source="plan_response",
            epic_launch_origin=epic_launch_origin,
        )
    except GateError as exc:
        code = (
            "conflict_already_handled"
            if exc.code in {"gate_cancelled", "already_answered"}
            else exc.code
        )
        raise PlanApprovalActionError(code, exc.target, str(exc)) from exc
    if execution.already_completed:
        raise PlanApprovalActionError(
            "conflict_already_handled",
            notification.id,
            "response already exists",
        )
    from sase.plan_gate import translate_plan_gate_response

    translate_plan_gate_response(bundle_path, execution.response)
    message = plan_approval_response_message_for_selection(
        selected_option_ids, tier=tier
    )
    return PlanApprovalActionResult(
        notification_id=notification.id,
        response_file=RESPONSE_FILENAME,
        response_path=bundle_path / RESPONSE_FILENAME,
        response_json=execution.response,
        message=message,
        epic_launch_task_id=(
            str(execution.response["epic_launch_task_id"])
            if execution.response.get("epic_launch_task_id")
            else None
        ),
    )


def _write_json_once(
    response_path: Path,
    response_json: dict[str, Any],
    notification_id: str,
) -> None:
    """Write a JSON response without overwriting an existing approval."""
    try:
        with response_path.open("x", encoding="utf-8") as f:
            json.dump(response_json, f, indent=2)
            f.write("\n")
    except FileExistsError as exc:
        raise PlanApprovalActionError(
            "conflict_already_handled", notification_id, "response already exists"
        ) from exc


def dismiss_notification_best_effort(notification_id: str) -> None:
    try:
        from sase.notifications import mark_dismissed

        mark_dismissed(notification_id)
    except Exception:
        pass


def _mark_action_handled_best_effort(
    notification_id: str,
    *,
    source: str,
    action: str | None = None,
) -> None:
    """Record that a notification action was resolved in the shared store."""
    try:
        from sase.notifications.pending_actions import mark_already_handled

        mark_already_handled(notification_id, source=source, action=action)
    except Exception:
        pass


def run_plan_side_effects(
    notification: PlanApprovalActionContext,
    choice: str,
    response_path: Path,
    response_json: dict[str, Any],
    *,
    response_container: dict[str, Any] | None = None,
    source: str = "plan_response",
) -> None:
    dismiss_notification_best_effort(notification.id)
    _mark_action_handled_best_effort(notification.id, source=source, action=choice)

    persisted_action = _persist_plan_approved_metadata(notification, response_json)
    if persisted_action is None:
        return

    _sync_reviewed_plan_to_durable_best_effort(notification)

    if approval_choice_archives_plan(choice):
        saved_path = _archive_plan_for_approval(notification, persisted_action)
        if saved_path:
            try:
                response_json["saved_plan_path"] = saved_path
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


def _sync_reviewed_plan_to_durable_best_effort(
    notification: PlanApprovalActionContext,
) -> None:
    """Copy reviewed bundle edits back to the durable proposal when known."""
    if not notification.host_files:
        return
    durable = durable_plan_file_for_context(notification)
    if durable is None:
        return
    reviewed = Path(notification.host_files[0]).expanduser()
    if reviewed.resolve(strict=False) == durable.resolve(strict=False):
        return
    try:
        content = reviewed.read_text(encoding="utf-8")
        durable.parent.mkdir(parents=True, exist_ok=True)
        durable.write_text(content, encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        _logger.warning(
            "Failed to sync reviewed plan %s to durable proposal %s",
            reviewed,
            durable,
            exc_info=True,
        )


def _persist_plan_approved_metadata(
    notification: PlanApprovalActionContext,
    response_json: dict[str, Any],
) -> str | None:
    action = persisted_plan_action(response_json)
    if action is None:
        return None

    artifacts_dir = resolve_plan_agent_artifacts_dir(notification.host_action_data)
    if artifacts_dir:
        meta_path = Path(artifacts_dir) / "agent_meta.json"
    else:
        raw_response_dir = notification.host_action_data.get("response_dir")
        if not raw_response_dir:
            return action
        meta_path = Path(raw_response_dir).expanduser().parent / "agent_meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            meta = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        meta = {}

    meta["plan_approved"] = True
    meta["plan_action"] = action
    canonicalize_agent_tribe_metadata(meta)
    try:
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        update_agent_artifact_index_for_marker_mutation(meta_path.parent)
    except OSError:
        pass
    return action


def _archive_plan_for_approval(
    notification: PlanApprovalActionContext,
    persisted_action: str,
) -> str | None:
    if not notification.host_files:
        return None
    try:
        from sase.running_field import get_workspace_directory
        from sase.sdd.files import (
            commit_sdd_store_files,
            ensure_bare_git_sdd_initialized,
        )
        from sase.sdd.plan_archive import archive_plan_file
        from sase.sdd.store import materialize_sdd_store

        project_dir = notification.host_action_data.get("project_dir")
        if not project_dir:
            return None
        artifacts_dir = resolve_plan_agent_artifacts_dir(notification.host_action_data)
        project_basename = os.path.basename(str(project_dir))
        workspace_dir = get_workspace_directory(project_basename, 1)
        sdd_store = materialize_sdd_store(workspace_dir, 1)
        if sdd_store.is_in_tree:
            ensure_bare_git_sdd_initialized(
                workspace_dir,
                commit=True,
                push=False,
            )
        tier: Literal["tale", "epic"] = "epic" if persisted_action == "epic" else "tale"
        src_plan = durable_plan_file_for_context(notification) or Path(
            notification.host_files[0]
        )
        archived = archive_plan_file(
            src_plan,
            sdd_store,
            tier=tier,
            preserve_existing=False,
            expect_prompt_snapshot=(tier == "epic"),
        )
        if not sdd_store.is_in_tree:
            commit_sdd_store_files(
                sdd_store,
                f"Archive approved plan {src_plan.stem}",
                paths=[archived.path],
                artifacts_dir=artifacts_dir,
            )
        return str(archived.path)
    except Exception:
        _logger.warning(
            "Failed to archive approved plan %s",
            notification.host_files[0],
            exc_info=True,
        )
        return None
