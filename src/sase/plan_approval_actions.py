"""Shared plan approval response orchestration and side effects.

The public API remains in this module while protocol, artifact-resolution, and
epic-launch details live in focused implementation modules.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
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
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.plan_approval_choices import (
    plan_approval_response_message_for_selection,
    plan_approval_selection_for_choice,
)

if TYPE_CHECKING:
    from sase.bead.epic_launch import EpicLaunchOrigin, EpicLaunchSubmission

_logger = logging.getLogger(__name__)
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
    epic_launch_mode: EpicLaunchMode = "launch",
    epic_launch_origin: EpicLaunchOrigin = "api",
    option_inputs: Mapping[str, Mapping[str, Any]] | None = None,
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
    epic_launch_project: str | None = None
    if choice == "epic":
        can_claim_epic_launch(notification, mode=epic_launch_mode)
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
    option_inputs: Mapping[str, Mapping[str, Any]] | None = None,
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
    from sase.gate_shell.log import bind_gate_shell_execution_callbacks
    from sase.gate_shell.settlement import settle_gate_shell
    from sase.gate_shell.store import find_gate_shell_by_gate_id

    shell_backed = isinstance(envelope.get("shell"), dict)
    gate_shell = (
        find_gate_shell_by_gate_id(None, str(envelope.get("request_id") or ""))
        if shell_backed
        else None
    )
    execution_kwargs: dict[str, Any] = (
        {}
        if gate_shell is None
        else bind_gate_shell_execution_callbacks(gate_shell.artifacts_dir).as_kwargs()
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

    # `option_inputs` only carries fields a declared-input plan option collects
    # -- none do today (see the ACE gate-inputs phase's deviation note) -- so
    # this branch is inert on landing and every existing call keeps taking the
    # `input_data`-only path below unchanged.
    per_option_inputs = (
        {
            option_id: {**input_data, **dict((option_inputs or {}).get(option_id, {}))}
            for option_id in selected_option_ids
        }
        if option_inputs and any(option_inputs.values())
        else None
    )
    try:
        execution = execute_gate_selection(
            bundle_path,
            selected_option_ids,
            None if per_option_inputs is not None else input_data,
            feedback=feedback,
            source="plan_response",
            epic_launch_origin=epic_launch_origin,
            option_inputs=per_option_inputs,
            **execution_kwargs,
        )
    except GateError as exc:
        code = (
            "conflict_already_handled"
            if exc.code in {"gate_cancelled", "already_answered"}
            else exc.code
        )
        raise PlanApprovalActionError(code, exc.target, str(exc)) from exc
    if gate_shell is not None:
        settle_gate_shell(
            gate_shell,
            gate_state="answered",
            reason="plan approval answered",
        )
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
        epic_launch_monitor_id=(
            str(execution.response["epic_launch_monitor_id"])
            if execution.response.get("epic_launch_monitor_id")
            else None
        ),
        epic_launch_task_id=(
            str(execution.response["epic_launch_task_id"])
            if execution.response.get("epic_launch_task_id")
            else None
        ),
    )


def _epic_launch_submission_ids(
    launch: EpicLaunchSubmission | None,
) -> tuple[str | None, str | None]:
    if launch is None:
        return None, None
    monitor_id = getattr(launch, "monitor_id", None)
    if monitor_id:
        return str(monitor_id), None
    task_id = getattr(launch, "task_id", None)
    if task_id:
        return None, str(task_id)
    return None, None


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
        return

    if response_json.get("action") in {"approve", "epic"}:
        response_json["plan_archive_owner"] = "none"
        response_json["plan_archive_state"] = "not_requested"


def apply_plan_post_terminal_side_effects(
    notification: PlanApprovalActionContext,
    choice: str,
    *,
    source: str = "plan_response",
) -> None:
    dismiss_notification_best_effort(notification.id)
    _mark_action_handled_best_effort(notification.id, source=source, action=choice)


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
    *,
    required: bool = False,
) -> str | None:
    if not notification.host_files:
        if required:
            raise PlanApprovalActionError(
                "invalid_request",
                "plan_file",
                "plan file is missing",
            )
        return None
    tier: Literal["tale", "epic"] = "epic" if persisted_action == "epic" else "tale"
    src_plan = durable_plan_file_for_context(notification) or Path(
        notification.host_files[0]
    )
    try:
        from sase._plan_archive_approval import archive_approved_plan

        return archive_approved_plan(
            notification.host_action_data,
            src_plan,
            tier=tier,
        )
    except Exception as error:
        from sase._plan_archive_approval import report_plan_archive_failure

        report_plan_archive_failure(src_plan, notification.host_action_data, error)
        if required:
            raise PlanApprovalActionError(
                "plan_archive_failed",
                str(src_plan),
                f"failed to archive approved plan: {error}",
            ) from error
        return None
