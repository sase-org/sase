"""Notification action handlers for the ace TUI app.

Dispatches notification actions: JumpToChangeSpec, JumpToAgent, Tmux, HITL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.notifications import Notification

    from ...models import Agent


def _find_agent_for_notification(
    app: object, notification: Notification
) -> Agent | None:
    """Find the agent matching a notification's identity fields.

    Matches by agent_cl_name + agent_timestamp in action_data against
    the currently loaded agents list.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            agent_cl_name and optionally agent_timestamp.

    Returns:
        The matching Agent, or None if not found.
    """
    cl_name = notification.action_data.get("agent_cl_name")
    if not cl_name:
        return None

    agent_timestamp = notification.action_data.get("agent_timestamp")

    # Normalize timestamp to 14-digit format for comparison with
    # agent.raw_suffix (which is always normalized to 14-digit).
    from ...models._timestamps import normalize_to_14_digit

    agent_timestamp = normalize_to_14_digit(agent_timestamp)

    agents: list[Agent] = app._agents  # type: ignore[attr-defined]
    for agent in agents:
        if agent.cl_name != cl_name:
            continue
        if agent_timestamp and agent.raw_suffix != agent_timestamp:
            continue
        return agent

    return None


def handle_jump_to_agent(app: object, notification: Notification) -> bool:
    """Jump to the agent referenced in the notification.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing cl_name,
            and optionally agent_type and raw_suffix for precise matching.

    Returns:
        True if the agent was found and selected.
    """
    cl_name = notification.action_data.get("cl_name")
    if not cl_name:
        app.notify("No cl_name in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    app.current_tab = "agents"  # type: ignore[attr-defined]

    agent_type = notification.action_data.get("agent_type")
    raw_suffix = notification.action_data.get("raw_suffix")

    agents = app._agents  # type: ignore[attr-defined]
    for idx, agent in enumerate(agents):
        if agent.cl_name != cl_name:
            continue
        if agent_type and agent.agent_type.value != agent_type:
            continue
        if raw_suffix and agent.raw_suffix != raw_suffix:
            continue
        app.current_idx = idx  # type: ignore[attr-defined]
        return True

    app.notify(f"Agent '{cl_name}' not found", severity="warning")  # type: ignore[attr-defined]
    return False


def handle_jump_to_changespec(app: object, notification: Notification) -> bool:
    """Jump to the changespec referenced in the notification.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing changespec_name.

    Returns:
        True if the changespec was found and selected.
    """
    changespec_name = notification.action_data.get("changespec_name")
    if not changespec_name:
        app.notify("No changespec_name in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    project_file = notification.action_data.get("project_file", "")
    return navigate_to_changespec_tab(app, changespec_name, project_file)


def navigate_to_changespec_tab(
    app: object, changespec_name: str, project_file: str
) -> bool:
    """Navigate to a ChangeSpec in the CLs tab, changing query if needed.

    1. Switch to CLs tab
    2. Search for changespec_name in current filtered list
    3. If found, select it
    4. If NOT found, change query to ``project:<project> AND NOT status:SUBMITTED``,
       reload, and select it

    Args:
        app: The AceApp instance.
        changespec_name: The name of the ChangeSpec to navigate to.
        project_file: Path to the .gp project file (used to derive project name).

    Returns:
        True if the changespec was found and selected.
    """
    from pathlib import Path

    from ....query import parse_query, to_canonical_string
    from ....query_history import push_to_prev_stack, save_query_history

    app.current_tab = "changespecs"  # type: ignore[attr-defined]

    # Search in current filtered list
    changespecs = app.changespecs  # type: ignore[attr-defined]
    for idx, cs in enumerate(changespecs):
        if cs.name == changespec_name:
            app.current_idx = idx  # type: ignore[attr-defined]
            return True

    # Not found — change query to show the target ChangeSpec
    if not project_file:
        app.notify(  # type: ignore[attr-defined]
            f"ChangeSpec '{changespec_name}' not found", severity="warning"
        )
        return False

    project_name = Path(project_file).parent.name
    new_query = f"project:{project_name} AND NOT status:SUBMITTED"

    try:
        new_parsed = parse_query(new_query)
        new_canonical = to_canonical_string(new_parsed)
        current_canonical = app.canonical_query_string  # type: ignore[attr-defined]

        # Push old query to history so user can go back with ^
        if new_canonical != current_canonical:
            push_to_prev_stack(
                current_canonical,
                app._query_history,  # type: ignore[attr-defined]
            )
            save_query_history(app._query_history)  # type: ignore[attr-defined]

        app.parsed_query = new_parsed  # type: ignore[attr-defined]
        app.query_string = new_query  # type: ignore[attr-defined]
        app._load_changespecs()  # type: ignore[attr-defined]
        app._save_current_query()  # type: ignore[attr-defined]

        # Search again in the new list
        changespecs = app.changespecs  # type: ignore[attr-defined]
        for idx, cs in enumerate(changespecs):
            if cs.name == changespec_name:
                app.current_idx = idx  # type: ignore[attr-defined]
                return True

    except Exception as e:
        app.notify(  # type: ignore[attr-defined]
            f"Navigation error: {e}", severity="error"
        )
        return False

    app.notify(  # type: ignore[attr-defined]
        f"ChangeSpec '{changespec_name}' not found", severity="warning"
    )
    return False


def handle_tmux(app: object, notification: Notification) -> bool:
    """Open a tmux session for the workspace directory in the notification.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing workspace_dir.

    Returns:
        True if the tmux session was opened successfully.
    """
    import subprocess
    from pathlib import Path

    workspace_dir = notification.action_data.get("workspace_dir")
    if not workspace_dir:
        app.notify("No workspace_dir in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    session_name = Path(workspace_dir).name

    with app.suspend():  # type: ignore[attr-defined]
        try:
            subprocess.run(["tm", session_name], check=False)
        except FileNotFoundError:
            app.notify("tm command not found", severity="error")  # type: ignore[attr-defined]
            return False

    app.notify(f"Opened tmux for {session_name}")  # type: ignore[attr-defined]
    return True


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
            app.push_screen(PlanApprovalModal(plan_file), on_dismiss)  # type: ignore[attr-defined]
            return

        # Find matching agent for status override updates
        agent = _find_agent_for_notification(app, notification)

        # Reject without feedback: kill agent, no response file needed
        # (killing the process group also kills the plan_approve_handler)
        if result.action == "reject" and result.feedback is None:
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
        if result.feedback is not None:
            response_data["feedback"] = result.feedback

        # On approval, save plan to workspace .sase/plans/ directory
        if result.action == "approve" and notification.files:
            project_dir = notification.action_data.get("project_dir")
            if project_dir:
                import os
                import shutil

                project_basename = os.path.basename(project_dir)
                try:
                    from sase.running_field import get_workspace_directory

                    workspace_dir = get_workspace_directory(project_basename, 1)
                    plans_dir = Path(workspace_dir) / ".sase" / "plans"
                    plans_dir.mkdir(parents=True, exist_ok=True)
                    src_plan = Path(notification.files[0])
                    dest_plan = plans_dir / src_plan.name
                    shutil.copy2(str(src_plan), str(dest_plan))
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
                app._agent_status_overrides[agent.identity] = "PLAN APPROVED"  # type: ignore[attr-defined]
                # Persist approval to agent_meta.json so it survives TUI restarts
                _persist_plan_approved(agent)
            # For reject with feedback: keep "PLANNING" override (no change)
            app._load_agents()  # type: ignore[attr-defined]

    app.push_screen(PlanApprovalModal(plan_file), on_dismiss)  # type: ignore[attr-defined]
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


def _persist_plan_approved(agent: Agent) -> None:
    """Write plan_approved flag to agent_meta.json so it survives TUI restarts.

    Args:
        agent: The agent whose plan was approved.
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
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except OSError:
        pass
