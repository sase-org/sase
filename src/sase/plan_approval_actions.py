"""Shared plan approval response protocol and side effects."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.plan_approval_choices import (
    PLAN_APPROVAL_CLI_KINDS,
    approval_choice_archives_plan,
    require_plan_approval_choice,
)

PLAN_APPROVAL_KINDS = PLAN_APPROVAL_CLI_KINDS


@dataclass(frozen=True)
class PlanApprovalActionContext:
    id: str
    host_files: tuple[str, ...]
    host_action_data: dict[str, str]


@dataclass(frozen=True)
class PlanApprovalActionResult:
    notification_id: str
    response_file: str
    response_path: Path
    response_json: dict[str, Any]
    message: str


class PlanApprovalActionError(RuntimeError):
    """Deterministic host-side plan action failure."""

    def __init__(self, code: str, target: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.target = target


def execute_plan_approval_response(
    notification: PlanApprovalActionContext,
    choice: str,
    *,
    feedback: str | None = None,
    commit_plan: bool | None = None,
    run_coder: bool | None = None,
    coder_prompt: str | None = None,
    coder_model: str | None = None,
    selected_member_ids: Sequence[str] | None = None,
) -> PlanApprovalActionResult:
    """Write the runner response for a resolved PlanApproval notification."""
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

    response_json, message = _plan_response_json(
        choice,
        feedback=feedback,
        commit_plan=commit_plan,
        run_coder=run_coder,
        coder_prompt=coder_prompt,
        coder_model=coder_model,
        selected_member_ids=selected_member_ids,
    )
    response_path = response_dir / "plan_response.json"
    _write_json_once(response_path, response_json, notification.id)

    run_plan_side_effects(notification, choice, response_path, response_json)
    return PlanApprovalActionResult(
        notification_id=notification.id,
        response_file="plan_response.json",
        response_path=response_path,
        response_json=response_json,
        message=message,
    )


def _plan_response_json(
    choice: str,
    *,
    feedback: str | None,
    commit_plan: bool | None,
    run_coder: bool | None,
    coder_prompt: str | None,
    coder_model: str | None,
    selected_member_ids: Sequence[str] | None,
) -> tuple[dict[str, Any], str]:
    """Map a product-level plan choice to the existing runner protocol."""
    try:
        record = require_plan_approval_choice(choice)
    except KeyError as exc:
        raise PlanApprovalActionError(
            "unsupported_action", choice, "unsupported plan action choice"
        ) from exc

    if record.protocol is not None:
        protocol = record.protocol
        response: dict[str, Any] = {
            "action": protocol.action,
            "commit_plan": protocol.commit_plan,
            "run_coder": protocol.run_coder,
        }
        if record.allow_protocol_overrides:
            if commit_plan is not None:
                response["commit_plan"] = commit_plan
            if run_coder is not None:
                response["run_coder"] = run_coder
        if record.allow_coder_options:
            _add_optional_coder_fields(
                response, coder_prompt=coder_prompt, coder_model=coder_model
            )
        _add_selected_member_ids(response, selected_member_ids)
        return response, record.response_message

    if choice == "reject":
        response = {"action": "reject"}
        if feedback is not None:
            response["feedback"] = feedback
        return response, record.response_message

    if choice == "feedback":
        if not feedback:
            raise PlanApprovalActionError(
                "invalid_request", "feedback", "feedback text is required"
            )
        return {"action": "reject", "feedback": feedback}, record.response_message

    raise PlanApprovalActionError(
        "unsupported_action", choice, "unsupported plan action choice"
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
    """Record that a notification action was resolved in the shared store.

    Best-effort so transports (e.g. Telegram) can later dismiss any inline
    keyboard they sent. Never raises — a failure must not block the runner
    response that the agent is waiting on.
    """
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
) -> None:
    dismiss_notification_best_effort(notification.id)
    _mark_action_handled_best_effort(
        notification.id, source="plan_response", action=choice
    )

    persisted_action = _persist_plan_approved_metadata(notification, response_json)
    if persisted_action is None:
        return

    if approval_choice_archives_plan(choice):
        saved_path = _archive_plan_for_approval(notification, persisted_action)
        if saved_path:
            try:
                response_json["saved_plan_path"] = saved_path
                response_path.write_text(
                    json.dumps(response_json, indent=2) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                pass


def _add_optional_coder_fields(
    response: dict[str, Any],
    *,
    coder_prompt: str | None,
    coder_model: str | None,
) -> None:
    if coder_prompt is not None:
        response["coder_prompt"] = coder_prompt
    if coder_model is not None:
        response["coder_model"] = coder_model


def _add_selected_member_ids(
    response: dict[str, Any],
    selected_member_ids: Sequence[str] | None,
) -> None:
    if selected_member_ids is None:
        return
    response["selected_member_ids"] = [
        member_id
        for member_id in selected_member_ids
        if isinstance(member_id, str) and member_id.strip()
    ]


def _persist_plan_approved_metadata(
    notification: PlanApprovalActionContext,
    response_json: dict[str, Any],
) -> str | None:
    action = persisted_plan_action(response_json)
    if action is None:
        return None

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
    try:
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        update_agent_artifact_index_for_marker_mutation(meta_path.parent)
    except OSError:
        pass
    return action


def persisted_plan_action(response_json: dict[str, Any]) -> str | None:
    """Return the canonical persisted action for a plan response."""
    return _persisted_plan_action(response_json)


def _persisted_plan_action(response_json: dict[str, Any]) -> str | None:
    action = response_json.get("action")
    if action in {"epic", "legend"}:
        return str(action)
    if action != "approve":
        return None

    if response_json.get("run_coder", True) is False:
        return "commit"
    if response_json.get("commit_plan") is True:
        return "tale"
    return "approve"


def _archive_plan_for_approval(
    notification: PlanApprovalActionContext,
    persisted_action: str,
) -> str | None:
    if not notification.host_files:
        return None
    try:
        from sase.file_references import format_with_prettier
        from sase.llm_provider._plan_utils import add_create_time_frontmatter
        from sase.running_field import get_workspace_directory
        from sase.sdd.files import (
            ensure_bare_git_sdd_initialized,
            get_yyyymm,
        )
        from sase.sdd.store import resolve_sdd_store

        project_dir = notification.host_action_data.get("project_dir")
        if not project_dir:
            return None
        project_basename = os.path.basename(str(project_dir))
        workspace_dir = get_workspace_directory(project_basename, 1)
        sdd_store = resolve_sdd_store(workspace_dir, 1)
        sdd_dir = sdd_store.sdd_dir
        if sdd_store.is_in_tree:
            ensure_bare_git_sdd_initialized(
                workspace_dir,
                commit=True,
                push=False,
            )
        plan_kind = (
            "epics"
            if persisted_action == "epic"
            else "legends"
            if persisted_action == "legend"
            else "tales"
        )
        dest_dir = sdd_dir / plan_kind / get_yyyymm()
        dest_dir.mkdir(parents=True, exist_ok=True)
        src_plan = Path(notification.host_files[0])
        content = format_with_prettier(src_plan.read_text(encoding="utf-8"))
        dest = dest_dir / src_plan.name
        dest.write_text(add_create_time_frontmatter(content), encoding="utf-8")
        return str(dest)
    except Exception:
        return None
