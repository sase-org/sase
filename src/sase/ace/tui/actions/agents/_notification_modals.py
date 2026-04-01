"""Modal-based notification action handlers.

Dispatches HITL, user question, and plan approval actions that push modal screens.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent


def handle_hitl(app: object, notification: Notification) -> bool:
    """Show the HITL modal for the workflow step in the notification.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            artifacts_dir and workflow_name.

    Returns:
        True if the HITL modal was pushed (response handled asynchronously).
    """
    import json
    from pathlib import Path

    from sase.xprompt import HITLResult

    from ...modals import WorkflowHITLInput, WorkflowHITLModal

    artifacts_dir = notification.action_data.get("artifacts_dir")
    workflow_name = notification.action_data.get("workflow_name", "unknown")
    if not artifacts_dir:
        app.notify("No artifacts_dir in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    artifacts_path = Path(artifacts_dir)
    request_path = artifacts_path / "hitl_request.json"

    if not request_path.exists():
        app.notify("No HITL request found", severity="warning")  # type: ignore[attr-defined]
        return False

    try:
        with open(request_path, encoding="utf-8") as f:
            request_data = json.load(f)
    except Exception as e:
        app.notify(f"Error reading HITL request: {e}", severity="error")  # type: ignore[attr-defined]
        return False

    input_data = WorkflowHITLInput(
        step_name=request_data.get("step_name", "unknown"),
        step_type=request_data.get("step_type", "agent"),
        output=request_data.get("output", {}),
        workflow_name=workflow_name,
        has_output=request_data.get("has_output", False),
        output_types=request_data.get("output_types") or {},
    )

    def on_dismiss(result: object) -> None:
        if result is None:
            return
        if not isinstance(result, HITLResult):
            return

        # Handle edit action
        if result.action == "edit":
            edited_output = app._edit_hitl_output(request_data.get("output", {}))  # type: ignore[attr-defined]
            if edited_output is not None:
                result = HITLResult(action="edit", edited_output=edited_output)
            else:
                return

        # Write response file
        response_path = artifacts_path / "hitl_response.json"
        response_data: dict[str, object] = {
            "action": result.action,
            "approved": result.approved,
        }
        if result.edited_output is not None:
            response_data["edited_output"] = result.edited_output
        if result.feedback is not None:
            response_data["feedback"] = result.feedback

        try:
            with open(response_path, "w", encoding="utf-8") as f:
                json.dump(response_data, f, indent=2, default=str)
            app.notify(f"Sent {result.action} response")  # type: ignore[attr-defined]
        except Exception as e:
            app.notify(f"Error writing response: {e}", severity="error")  # type: ignore[attr-defined]

    app.push_screen(WorkflowHITLModal(input_data), on_dismiss)  # type: ignore[attr-defined]
    return True


def handle_user_question(app: object, notification: Notification) -> bool:
    """Show the user question modal for a Claude Code AskUserQuestion hook.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            response_dir and session_id.

    Returns:
        True if the user question modal was pushed.
    """
    import json
    from pathlib import Path

    from ...modals import UserQuestionModal, UserQuestionResult

    response_dir = notification.action_data.get("response_dir")
    if not response_dir:
        app.notify("No response_dir in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    response_path = Path(response_dir)
    request_path = response_path / "question_request.json"

    if not request_path.exists():
        app.notify("User question request expired or not found", severity="warning")  # type: ignore[attr-defined]
        return False

    try:
        with open(request_path, encoding="utf-8") as f:
            request_data = json.load(f)
    except Exception as e:
        app.notify(f"Error reading question request: {e}", severity="error")  # type: ignore[attr-defined]
        return False

    questions = request_data.get("questions", [])

    def on_dismiss(result: object) -> None:
        if result is None:
            return
        if not isinstance(result, UserQuestionResult):
            return

        # Build response data matching user_question_handler._format_answers format
        response_data: dict[str, object] = {
            "answers": [
                {
                    "question": a.question,
                    "selected": a.selected,
                    "custom_feedback": a.custom_feedback,
                }
                for a in result.answers
            ],
            "global_note": result.global_note,
        }

        question_response_path = response_path / "question_response.json"
        try:
            with open(question_response_path, "w", encoding="utf-8") as f:
                json.dump(response_data, f, indent=2)
            app.notify("Sent question response")  # type: ignore[attr-defined]
        except Exception as e:
            app.notify(f"Error writing response: {e}", severity="error")  # type: ignore[attr-defined]

        # Restore agent status override to pre-question value
        _restore_pre_question_status(app, notification)

    app.push_screen(UserQuestionModal(questions), on_dismiss)  # type: ignore[attr-defined]
    return True


def handle_plan_approval(app: object, notification: Notification) -> bool:
    """Show the plan approval modal for a Claude Code plan.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            response_dir and session_id.

    Returns:
        True if the plan approval modal was pushed.
    """
    import json
    from pathlib import Path

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

    # Get plan file path from notification files
    if not notification.files:
        app.notify("No plan file in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    plan_file = notification.files[0]

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
                PlanApprovalModal(plan_file),
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

        # Find matching agent for status override updates
        from ._notification_navigation import find_agent_for_notification

        agent = find_agent_for_notification(app, notification)

        # Reject without feedback: write response file so external watchers
        # (e.g. Telegram) can detect the rejection, then kill the agent.
        if result.action == "reject" and result.feedback is None:
            plan_response_path = response_path / "plan_response.json"
            plan_response_path.write_text(json.dumps({"action": "reject"}))

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

        # Write response file (for approve and reject with feedback)
        plan_response_path = response_path / "plan_response.json"
        response_data: dict[str, object] = {
            "action": result.action,
        }
        if result.action == "approve":
            response_data["commit_plan"] = result.commit_plan
            response_data["run_coder"] = result.run_coder
            if result.coder_prompt_extra is not None:
                response_data["coder_prompt_extra"] = result.coder_prompt_extra
        if result.feedback is not None:
            response_data["feedback"] = result.feedback

        # On approval, save plan to workspace .sase/plans/ directory
        if result.action in ("approve", "commit") and notification.files:
            project_dir = notification.action_data.get("project_dir")
            if project_dir:
                import os

                project_basename = os.path.basename(project_dir)
                try:
                    from sase.gemini_wrapper.file_references import (
                        format_with_prettier,
                    )
                    from sase.llm_provider._plan_utils import (
                        add_create_time_frontmatter,
                    )
                    from sase.running_field import get_workspace_directory

                    from sase.sdd.files import get_yyyymm

                    workspace_dir = get_workspace_directory(project_basename, 1)
                    yyyymm = get_yyyymm()
                    plans_dir = Path(workspace_dir) / ".sase" / "plans" / yyyymm
                    plans_dir.mkdir(parents=True, exist_ok=True)
                    src_plan = Path(notification.files[0])
                    dest_plan = plans_dir / src_plan.name
                    content = src_plan.read_text(encoding="utf-8")
                    content = format_with_prettier(content)
                    dest_plan.write_text(
                        add_create_time_frontmatter(content), encoding="utf-8"
                    )
                    response_data["saved_plan_path"] = str(dest_plan)
                except Exception:
                    pass  # Best effort

        try:
            with open(plan_response_path, "w", encoding="utf-8") as f:
                json.dump(response_data, f, indent=2)
            app.notify(f"Sent plan {result.action} response")  # type: ignore[attr-defined]
        except Exception as e:
            app.notify(f"Error writing response: {e}", severity="error")  # type: ignore[attr-defined]
            return

        # Dismiss notification to prevent re-polling
        from sase.notifications import mark_dismissed

        mark_dismissed(notification.id)

        # Update status override based on action
        if agent is not None:
            if result.action == "approve":
                if result.run_coder:
                    app._agent_status_overrides[agent.identity] = "PLAN APPROVED"  # type: ignore[attr-defined]
                    persist_plan_approved(agent, action="approve")
                elif result.commit_plan:
                    app._agent_status_overrides[agent.identity] = "PLAN COMMITTED"  # type: ignore[attr-defined]
                    # Keep legacy action metadata for commit-only outcomes.
                    persist_plan_approved(agent, action="commit")
                else:
                    app._agent_status_overrides[agent.identity] = "PLAN APPROVED"  # type: ignore[attr-defined]
                    persist_plan_approved(agent, action="approve")
            elif result.action == "commit":
                app._agent_status_overrides[agent.identity] = "PLAN COMMITTED"  # type: ignore[attr-defined]
                persist_plan_approved(agent, action="commit")
            elif result.action == "epic":
                app._agent_status_overrides[agent.identity] = "EPIC CREATED"  # type: ignore[attr-defined]
                persist_plan_approved(agent, action="epic")
            elif result.feedback is not None:
                # Reject with feedback: agent is resuming, mark as RUNNING
                app._agent_status_overrides[agent.identity] = "RUNNING"  # type: ignore[attr-defined]
            app._load_agents()  # type: ignore[attr-defined]

    app.push_screen(  # type: ignore[attr-defined]
        PlanApprovalModal(plan_file), on_dismiss
    )
    return True


def _restore_pre_question_status(app: object, notification: Notification) -> None:
    """Restore agent status override after a user question is answered.

    Looks up the agent's pre-question status and either restores it as the
    override (e.g. "PLAN APPROVED") or removes the override entirely (reverting
    the agent to its disk status, e.g. "RUNNING").
    """
    cl_name = notification.action_data.get("agent_cl_name")
    if not cl_name:
        return

    agent_timestamp = notification.action_data.get("agent_timestamp")

    # Normalize timestamp to 14-digit format for comparison with
    # agent.raw_suffix (which is always normalized to 14-digit).
    from ...models._timestamps import normalize_to_14_digit

    agent_timestamp = normalize_to_14_digit(agent_timestamp)

    # Find matching agent to get identity
    for agent in app._agents:  # type: ignore[attr-defined]
        if agent.cl_name != cl_name:
            continue
        if agent_timestamp and agent.raw_suffix != agent_timestamp:
            continue

        identity = agent.identity
        pre_status = app._agent_pre_question_status.pop(identity, None)  # type: ignore[attr-defined]
        if pre_status is not None:
            # Restore previous override (e.g. "PLAN APPROVED")
            app._agent_status_overrides[identity] = pre_status  # type: ignore[attr-defined]
        else:
            # No previous override — remove it so agent reverts to disk status
            app._agent_status_overrides.pop(identity, None)  # type: ignore[attr-defined]

        # Reload agents to apply the restored status
        app._load_agents()  # type: ignore[attr-defined]
        break


def persist_plan_approved(agent: Agent, action: str = "approve") -> None:
    """Write plan_approved flag to agent_meta.json so it survives TUI restarts.

    Args:
        agent: The agent whose plan was approved.
        action: The plan action taken — "approve", "commit", or "epic".
    """
    import json
    from pathlib import Path

    artifacts_dir = agent.artifacts_dir or agent.get_artifacts_dir()
    if not artifacts_dir:
        return

    meta_path = Path(artifacts_dir) / "agent_meta.json"
    meta: dict[str, object] = {}
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    meta["plan_approved"] = True
    meta["plan_action"] = action
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except OSError:
        pass
