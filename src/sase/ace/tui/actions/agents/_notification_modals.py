"""Modal-based notification action handler exports.

Keeps historical imports stable while focused modules handle individual flows.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

from ._notification_hitl_modal import handle_hitl as handle_hitl
from ._notification_launch_approval import (
    handle_launch_approval as handle_launch_approval,
)
from ._notification_modal_responses import write_workflow_action_response
from ._notification_plan_persistence import (
    persist_plan_approved as persist_plan_approved,
)
from ._notification_question_modal import (
    handle_user_question as handle_user_question,
    open_user_question_modal_from_marker as open_user_question_modal_from_marker,
)
from ._notification_utils import (
    refresh_notification_agent_from_cache,
    refresh_notification_agent_or_request,
)
from sase.plan_approval_choices import (
    PlanApprovalModalChoice,
    approval_choice_archives_plan,
    approval_choice_persist_action,
    approval_choice_status_label,
    approval_protocol_for_choice,
    member_options_from_request_data,
)

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent
    from ...modals import PlanApprovalResult


log = logging.getLogger(__name__)


def handle_plan_approval(
    app: object,
    notification: Notification,
    pending_approve_state: object | None = None,
) -> bool:
    """Show the plan approval modal for a Claude Code plan.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            response_dir and session_id.
        pending_approve_state: Optional PendingApproveState to auto-push
            the custom approval modal with restored state.

    Returns:
        True if the plan approval modal was pushed.
    """
    from ...modals import PlanApprovalModal, PlanApprovalResult

    response_dir = notification.action_data.get("response_dir")
    if not response_dir:
        app.notify("No response_dir in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    response_path = Path(response_dir)
    request_path = response_path / "plan_request.json"

    if not request_path.exists():
        app.notify("Plan approval request expired or not found", severity="warning")  # type: ignore[attr-defined]
        return False
    request_data = _read_plan_request_data(request_path)
    member_options = member_options_from_request_data(request_data)

    # Get plan file path from notification files
    if not notification.files:
        app.notify("No plan file in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    plan_file = notification.files[0]
    llm_provider = notification.action_data.get("llm_provider")
    model = notification.action_data.get("model")
    from sase.sdd.plan_tiers import read_plan_tier

    authored_tier = read_plan_tier(Path(plan_file).expanduser())
    default_choice = (
        cast(PlanApprovalModalChoice, authored_tier)
        if authored_tier in {"tale", "epic"}
        else None
    )

    def on_dismiss(result: object) -> None:
        if result is None:
            return
        if not isinstance(result, PlanApprovalResult):
            return

        # Handle edit action: open editor, then re-push modal
        if result.action == "edit":
            import os
            import subprocess

            editor = os.environ.get("EDITOR") or "nvim"
            with app.suspend():  # type: ignore[attr-defined]
                subprocess.run([editor, plan_file], check=False)
            app.push_screen(  # type: ignore[attr-defined]
                PlanApprovalModal(
                    plan_file,
                    llm_provider=llm_provider,
                    model=model,
                    member_options=member_options,
                    default_choice=default_choice,
                ),
                on_dismiss,
            )
            return

        # Feedback requested: dismiss modal and mount PromptInputBar in feedback mode
        if result.action == "feedback_requested":
            from ._notification_navigation import find_agent_for_notification as _find

            from ...widgets import PromptInputBar

            agent = _find(app, notification)
            agent_identity = agent.identity if agent is not None else None

            from ._types import PlanFeedbackContext

            app._plan_feedback_context = PlanFeedbackContext(  # type: ignore[attr-defined]
                notification_id=notification.id,
                response_path=response_path,
                agent_identity=agent_identity,
                plan_file=plan_file,
            )
            app.mount(PromptInputBar(mode="feedback", id="prompt-input-bar"))  # type: ignore[attr-defined]
            return

        # Approve prompt edit: delegate prompt editing to PromptInputBar
        if result.action == "approve_prompt_edit":
            from ...widgets import PromptInputBar

            from ._types import ApprovePromptContext

            app._approve_prompt_context = ApprovePromptContext(  # type: ignore[attr-defined]
                notification=notification,
                plan_file=plan_file,
                commit_plan=result.commit_plan,
                run_coder=result.run_coder,
                current_prompt=result.coder_prompt or "",
                coder_model=result.coder_model,
                choice=result.choice,
                selected_member_ids=result.selected_member_ids,
            )
            app.mount(  # type: ignore[attr-defined]
                PromptInputBar(
                    initial_value=result.coder_prompt or "",
                    mode="approve_prompt",
                    id="prompt-input-bar",
                )
            )
            return

        # Find matching agent for status override updates
        from ._notification_navigation import find_agent_for_notification

        agent = find_agent_for_notification(app, notification)

        # Reject without feedback: write response file so external watchers
        # (e.g. Telegram) can detect the rejection, then kill the agent.
        if result.action == "reject" and result.feedback is None:
            plan_response_path = response_path / "plan_response.json"
            write_workflow_action_response(
                plan_response_path,
                {"action": "reject"},
                action_kind="plan_approval",
                notification_id=notification.id,
            )

            from sase.notifications import mark_dismissed

            mark_dismissed(notification.id)
            if agent is not None:
                # Clear overrides before kill (_do_kill_agent calls _load_agents)
                app._agent_status_overrides.pop(agent.identity, None)  # type: ignore[attr-defined]
                app._agent_pre_question_status.pop(agent.identity, None)  # type: ignore[attr-defined]
                app._do_kill_agent(agent)  # type: ignore[attr-defined]
            else:
                app.notify("Rejected plan (agent not found)")  # type: ignore[attr-defined]
            return

        # Write response file (for approve and reject with feedback). This is
        # the latency-sensitive part: blocked agent runners watch this file.
        plan_response_path = response_path / "plan_response.json"
        response_data = _build_plan_approval_response(result)

        choice = _plan_approval_choice_for_status(result)
        if choice in {"tale", "epic"}:
            from sase.plan_approval_actions import (
                PlanApprovalValidationError,
                require_plan_approval_validation,
            )

            try:
                require_plan_approval_validation(plan_file, choice)
            except PlanApprovalValidationError as exc:
                app.notify(  # type: ignore[attr-defined]
                    str(exc),
                    title=f"{choice.title()} approval blocked",
                    severity="error",
                    timeout=15,
                )
                return

        try:
            write_workflow_action_response(
                plan_response_path,
                response_data,
                action_kind="plan_approval",
                notification_id=notification.id,
            )
            app.notify(f"Sent plan {result.action} response")  # type: ignore[attr-defined]
        except Exception as e:
            app.notify(f"Error writing response: {e}", severity="error")  # type: ignore[attr-defined]
            return

        # Update the visible status from cached in-memory data immediately.
        if agent is not None:
            status = _plan_approval_status(result)
            if status is not None:
                app._agent_status_overrides[agent.identity] = status  # type: ignore[attr-defined]
                _refresh_agents_from_cache(app, agent)

        _start_plan_approval_background_worker(
            app,
            notification,
            agent,
            result,
            plan_response_path,
        )

    app.push_screen(  # type: ignore[attr-defined]
        PlanApprovalModal(
            plan_file,
            pending_approve_state=pending_approve_state,  # type: ignore[arg-type]
            llm_provider=llm_provider,
            model=model,
            member_options=member_options,
            default_choice=default_choice,
        ),
        on_dismiss,
    )
    return True


def _build_plan_approval_response(result: PlanApprovalResult) -> dict[str, object]:
    """Build the JSON response for a plan approval modal result."""
    action, commit_plan, run_coder = _plan_approval_protocol_fields(result)
    response_data: dict[str, object] = {
        "action": action,
    }
    if result.feedback is not None:
        response_data["feedback"] = result.feedback
    response_data["commit_plan"] = commit_plan
    response_data["run_coder"] = run_coder
    if result.coder_prompt is not None:
        response_data["coder_prompt"] = result.coder_prompt
    if result.coder_model is not None:
        response_data["coder_model"] = result.coder_model
    if result.selected_member_ids is not None:
        response_data["selected_member_ids"] = list(result.selected_member_ids)
    return response_data


def _read_plan_request_data(request_path: Path) -> dict[str, object]:
    """Read the small plan request payload for modal option rendering."""
    import json

    try:
        with request_path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _plan_approval_protocol_fields(
    result: PlanApprovalResult,
) -> tuple[str, bool, bool]:
    """Return runner-facing action, commit flag, and coder flag."""
    if result.choice is not None:
        protocol = approval_protocol_for_choice(result.choice)
        return protocol.action, protocol.commit_plan, protocol.run_coder

    if result.action == "epic":
        return result.action, True, True

    return result.action, result.commit_plan, result.run_coder


def _plan_tier_for_action(action: str) -> str:
    return "epic" if action == "epic" else "tale"


def _archive_plan_for_approval(
    notification: Notification, action: str = "approve"
) -> str | None:
    """Best-effort copy of an approved plan into the workspace plan archive."""
    import os

    project_dir = notification.action_data.get("project_dir")
    if not project_dir or not notification.files:
        return None

    try:
        from sase.file_references import format_with_prettier
        from sase.llm_provider._plan_utils import add_create_time_frontmatter
        from sase.plan_approval_actions import resolve_plan_agent_artifacts_dir
        from sase.running_field import get_workspace_directory
        from sase.sdd.files import (
            commit_sdd_store_files,
            ensure_bare_git_sdd_initialized,
            get_yyyymm,
        )
        from sase.sdd.store import materialize_sdd_store

        project_basename = os.path.basename(str(project_dir))
        workspace_dir = get_workspace_directory(project_basename, 1)
        sdd_store = materialize_sdd_store(workspace_dir, 1)
        if sdd_store.is_in_tree:
            ensure_bare_git_sdd_initialized(
                workspace_dir,
                commit=True,
                push=False,
            )
        yyyymm = get_yyyymm()
        plans_dir = sdd_store.kind_root("plans") / yyyymm
        src_plan = Path(notification.files[0])
        dest_plan = plans_dir / src_plan.name
        content = src_plan.read_text(encoding="utf-8")
        content = format_with_prettier(content)
        from sase.sdd.committed_plan_validation import validate_plan_for_commit
        from sase.sdd.frontmatter import set_frontmatter_fields

        content = add_create_time_frontmatter(content)
        tier = _plan_tier_for_action(action)
        content = set_frontmatter_fields(content, {"tier": tier})
        validate_plan_for_commit(
            content,
            tier=tier,
            path=dest_plan,
            yyyymm=yyyymm,
        )
        plans_dir.mkdir(parents=True, exist_ok=True)
        dest_plan.write_text(content, encoding="utf-8")
        if not sdd_store.is_in_tree:
            artifacts_dir = resolve_plan_agent_artifacts_dir(notification.action_data)
            commit_sdd_store_files(
                sdd_store,
                f"Archive approved plan {src_plan.stem}",
                paths=[dest_plan],
                push_after_commit="async",
                artifacts_dir=artifacts_dir,
            )
        return str(dest_plan)
    except Exception:
        log.debug("Failed to archive approved plan", exc_info=True)
        return None


def _plan_approval_status(result: PlanApprovalResult) -> str | None:
    """Return the immediate status override for a plan approval result."""
    choice = _plan_approval_choice_for_status(result)
    if choice is not None:
        return approval_choice_status_label(choice)
    if result.feedback is not None:
        return "RUNNING"
    return None


def _plan_approval_persist_action(result: PlanApprovalResult) -> str | None:
    """Return the persisted plan action marker for a result, if any."""
    choice = _plan_approval_choice_for_status(result)
    return None if choice is None else approval_choice_persist_action(choice)


def _plan_approval_choice_for_status(result: PlanApprovalResult) -> str | None:
    """Infer the product-level approval choice for status/persist labels."""
    if result.choice is not None:
        return result.choice
    if result.action == "approve" and result.commit_plan and not result.run_coder:
        return "commit"
    if result.action == "approve" and result.commit_plan and result.run_coder:
        return "tale"
    if result.action == "approve" and not result.commit_plan and result.run_coder:
        return "approve"
    if result.action == "epic":
        return result.action
    return None


def _refresh_agents_from_cache(app: object, agent: Agent | None = None) -> None:
    """Refresh visible agents without forcing disk I/O on the keypress path."""
    if refresh_notification_agent_from_cache(app, agent=agent):
        return

    refresh_notification_agent_or_request(app, agent=agent)


def _start_plan_approval_background_worker(
    app: object,
    notification: Notification,
    agent: Agent | None,
    result: PlanApprovalResult,
    plan_response_path: Path,
) -> None:
    """Run non-critical plan approval side effects off the TUI keypress path."""

    def work() -> str | None:
        saved_plan_path: str | None = None
        try:
            from sase.notifications import mark_dismissed

            mark_dismissed(notification.id)
        except Exception:
            log.warning("Failed to dismiss plan approval notification", exc_info=True)

        persist_action = _plan_approval_persist_action(result)
        if agent is not None and persist_action is not None:
            try:
                persist_plan_approved(agent, action=persist_action)
            except Exception:
                log.warning("Failed to persist plan approval marker", exc_info=True)

        choice = _plan_approval_choice_for_status(result)
        if choice is not None and approval_choice_archives_plan(choice):
            saved_plan_path = _archive_plan_for_approval(notification, result.action)
            if saved_plan_path is not None:
                _add_saved_plan_to_response(plan_response_path, saved_plan_path)

        _call_on_app_thread(
            app,
            lambda: _finish_plan_approval_background_work(
                app,
                result,
                saved_plan_path,
            ),
        )
        return saved_plan_path

    run_worker = getattr(app, "run_worker", None)
    if callable(run_worker):
        try:
            run_worker(work, thread=True)
            return
        except Exception:
            log.debug(
                "Falling back to synchronous plan approval side effects", exc_info=True
            )

    work()


def _add_saved_plan_to_response(plan_response_path: Path, saved_plan_path: str) -> None:
    """Add the archived path to the response file after the fast write."""
    import json

    try:
        with open(plan_response_path, encoding="utf-8") as f:
            response_data = json.load(f)
        if not isinstance(response_data, dict):
            return
        response_data["saved_plan_path"] = saved_plan_path
        with open(plan_response_path, "w", encoding="utf-8") as f:
            json.dump(response_data, f, indent=2)
    except Exception:
        log.debug("Failed to update plan response with saved plan path", exc_info=True)


def _call_on_app_thread(app: object, callback: object) -> None:
    """Invoke a UI callback from worker threads when Textual support exists."""
    call_from_thread = getattr(app, "call_from_thread", None)
    if callable(call_from_thread):
        try:
            call_from_thread(callback)
            return
        except Exception:
            log.debug("Failed to schedule app-thread callback", exc_info=True)
    if callable(callback):
        callback()


def _finish_plan_approval_background_work(
    app: object,
    result: PlanApprovalResult,
    saved_plan_path: str | None,
) -> None:
    """Apply UI-only follow-up after background approval work completes."""
    if (
        result.action == "approve"
        and not result.run_coder
        and result.commit_plan
        and saved_plan_path is not None
    ):
        from sase.ace.tui.actions.clipboard import copy_to_system_clipboard

        short_path = saved_plan_path.replace(str(Path.home()), "~")
        copy_to_system_clipboard(short_path)
        app.notify(f"Plan committed — path copied: {short_path}")  # type: ignore[attr-defined]

    refresh_count = getattr(app, "_refresh_notification_count", None)
    if callable(refresh_count):
        refresh_count()
