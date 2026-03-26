"""Helper utilities for the agent runner.

Pure utility functions for workflow state extraction, marker files,
follow-up artifacts, and question flows.
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from sase.axe.runner_utils import was_killed
from sase.artifacts import create_artifacts_directory


def is_workflow_noop(artifacts_dir: str) -> bool:
    """Check if a completed workflow launched zero agents.

    Reads agents_launched from workflow_state.json. A workflow that completed
    successfully but never invoked an LLM agent (e.g. a for-loop with an empty
    list) is considered a noop.

    Args:
        artifacts_dir: Path to the artifacts directory containing workflow_state.json.

    Returns:
        True if the workflow launched zero agents, False otherwise.
    """
    state_path = os.path.join(artifacts_dir, "workflow_state.json")
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    return data.get("agents_launched", -1) == 0


def extract_step_output_and_diff_path(
    artifacts_dir: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Extract step_output and diff_path from workflow_state.json.

    Reads the workflow state written by execute_workflow() and extracts:
    - step_output: the last completed step's output dict
    - diff_path: path value from output_types with field_type=="path",
      or fallback to direct diff_path key in step outputs

    Args:
        artifacts_dir: Path to the artifacts directory containing workflow_state.json.

    Returns:
        Tuple of (step_output, diff_path).
    """
    state_path = os.path.join(artifacts_dir, "workflow_state.json")
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None, None

    # Extract step_output: last step with a dict output
    step_output: dict[str, Any] | None = None
    for step_data in reversed(data.get("steps", [])):
        output = step_data.get("output")
        if output and isinstance(output, dict):
            step_output = output
            break

    # Extract diff_path: search backward through all steps for a
    # "diff_path" output.  This handles embedded workflows (e.g.
    # #gh + #pr) where the diff step is not the last step.
    diff_path: str | None = None
    steps_list = data.get("steps", [])
    for step_data in reversed(steps_list):
        step_out = step_data.get("output")
        if isinstance(step_out, dict) and step_out.get("diff_path"):
            diff_path = str(step_out["diff_path"])
            break

    # Fallback: last step's first path-typed output (for workflows
    # that use a different field name for their diff path).
    if not diff_path and steps_list:
        last_step = steps_list[-1]
        output_types = last_step.get("output_types") or {}
        step_out = last_step.get("output")
        if output_types and isinstance(step_out, dict):
            for field_name, field_type in output_types.items():
                if field_type == "path":
                    path_value = step_out.get(field_name)
                    if path_value:
                        diff_path = str(path_value)
                        break

    # Expand tilde in diff_path to prevent path corruption when absolutized
    if diff_path:
        diff_path = os.path.expanduser(diff_path)

    return step_output, diff_path


def read_and_delete_marker(artifacts_dir: str, filename: str) -> dict[str, Any] | None:
    """Read a JSON marker file, delete it, and return parsed data.

    Returns None if the file doesn't exist or can't be parsed.
    """
    path = os.path.join(artifacts_dir, filename)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        os.unlink(path)
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def update_meta_suffix(artifacts_dir: str, suffix: str) -> None:
    """Read agent_meta.json, set role_suffix, and write it back."""
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["role_suffix"] = suffix
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def promote_to_workflow(artifacts_dir: str, base_name: str) -> None:
    """Retroactively rename the initial agent to ``<base_name>.1``.

    Called when the first follow-up agent is created, promoting a
    single-agent run into a multi-agent workflow.  Sets both
    ``name`` and ``workflow_name`` in the agent's ``agent_meta.json``.
    """
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["name"] = f"{base_name}.1"
        meta["workflow_name"] = base_name
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def normalize_handoff_interruption_state(artifacts_dir: str) -> None:
    """Normalize SIGTERM-induced failed state before plan/question handoff.

    ``sase plan`` and ``sase questions`` intentionally SIGTERM the current agent
    process group so the runner can switch into approval/question mode.  The
    workflow executor may persist this as a failed step/workflow first
    (LLMInvocationError exit code -15 or 143).  This helper rewrites that transient
    state to completed so the TUI does not show a false failure.
    """

    def _is_sigterm_error(error: object) -> bool:
        if not isinstance(error, str):
            return False
        lowered = error.lower()
        # SIGTERM surfaces as exit code -15 (direct subprocess) or 143
        # (128+15, shell-wrapped) depending on how the LLM provider is
        # invoked.
        return (
            "exit code -15" in lowered
            or "exit code 143" in lowered
            or "sigterm" in lowered
        )

    state_path = Path(artifacts_dir) / "workflow_state.json"
    saw_sigterm_failure = False

    try:
        with open(state_path, encoding="utf-8") as f:
            state_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        state_data = None

    if isinstance(state_data, dict):
        changed = False
        for step_data in state_data.get("steps", []):
            if (
                isinstance(step_data, dict)
                and step_data.get("status") == "failed"
                and _is_sigterm_error(step_data.get("error"))
            ):
                saw_sigterm_failure = True
                step_data["status"] = "completed"
                step_data["error"] = None
                step_data["traceback"] = None
                changed = True

        if state_data.get("status") == "failed" and (
            saw_sigterm_failure or _is_sigterm_error(state_data.get("error"))
        ):
            state_data["status"] = "completed"
            state_data["error"] = None
            state_data["traceback"] = None
            changed = True

        if changed:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)

    if not saw_sigterm_failure:
        return

    for marker_path in Path(artifacts_dir).glob("prompt_step_*.json"):
        try:
            with open(marker_path, encoding="utf-8") as f:
                marker_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(marker_data, dict):
            continue
        if marker_data.get("status") != "failed":
            continue
        if not _is_sigterm_error(marker_data.get("error")):
            continue

        marker_data["status"] = "completed"
        marker_data["error"] = None
        marker_data["traceback"] = None
        try:
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump(marker_data, f, indent=2)
        except OSError:
            continue


def create_followup_artifacts(
    project_name: str,
    base_meta: dict[str, Any],
    suffix: str,
    prev_artifacts_timestamp: str,
    *,
    workspace_num: int | None = None,
    agent_name_override: str | None = None,
    workflow_name: str | None = None,
) -> str:
    """Create a new timestamped artifacts directory for a follow-up agent.

    Inherits metadata fields from the previous agent's meta and adds
    role_suffix and parent_timestamp.

    Returns the new artifacts_dir path.
    """
    from datetime import UTC, datetime

    new_artifacts_dir = create_artifacts_directory("ace-run", project_name=project_name)

    followup_meta: dict[str, Any] = {"pid": os.getpid()}
    for key in ("model", "llm_provider", "vcs_provider", "name", "approve"):
        if base_meta.get(key):
            followup_meta[key] = base_meta[key]
    if agent_name_override is not None:
        followup_meta["name"] = agent_name_override
    if workflow_name is not None:
        followup_meta["workflow_name"] = workflow_name
    followup_meta["role_suffix"] = suffix
    followup_meta["parent_timestamp"] = prev_artifacts_timestamp
    if workspace_num is not None:
        followup_meta["workspace_num"] = workspace_num
    followup_meta["run_started_at"] = datetime.now(UTC).isoformat()

    meta_path = os.path.join(new_artifacts_dir, "agent_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(followup_meta, f, indent=2)

    return new_artifacts_dir


def handle_questions_flow(
    questions: list[dict[str, Any]], artifacts_dir: str
) -> dict[str, Any] | None:
    """Handle the questions notification and polling flow.

    For auto-approve agents, auto-selects the first option per question.
    Otherwise, writes a question_request.json, sends notifications, and
    polls for question_response.json.

    Returns the response dict, or None if killed during polling.
    """
    from sase.main.plan_approve_handler import (
        get_tmux_prefix,
        is_auto_approve_active,
        ring_tmux_bell,
        send_desktop_notification,
    )

    # Auto-approve: pick first option for each question
    if is_auto_approve_active():
        answers = []
        for q in questions:
            options = q.get("options", [])
            selected = options[0]["label"] if options else ""
            answers.append(
                {
                    "question": q.get("question", ""),
                    "selected": selected,
                    "custom_feedback": None,
                }
            )
        return {"answers": answers, "global_note": ""}

    # Create response directory and write request
    session_id = str(uuid.uuid4())
    response_dir = os.path.expanduser(f"~/.sase/user_question/{session_id}")
    os.makedirs(response_dir, exist_ok=True)

    request_data = {
        "questions": questions,
        "session_id": session_id,
        "timestamp": time.time(),
    }
    request_path = os.path.join(response_dir, "question_request.json")
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump(request_data, f, indent=2)

    # Send notification
    from sase.notifications.senders import notify_user_question

    agent_cl_name = os.environ.get("SASE_AGENT_CL_NAME")
    agent_project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    agent_timestamp = os.environ.get("SASE_AGENT_TIMESTAMP")
    q_summary = "; ".join(q.get("question", "?") for q in questions[:3])
    notify_user_question(
        response_dir=response_dir,
        session_id=session_id,
        notes=q_summary,
        agent_cl_name=agent_cl_name,
        agent_project_file=agent_project_file,
        agent_timestamp=agent_timestamp,
    )

    prefix = get_tmux_prefix()
    send_desktop_notification(
        f"{prefix} Agent Question", "Agent has questions in sase ace"
    )
    ring_tmux_bell()

    # Poll for response
    response_path = os.path.join(response_dir, "question_response.json")
    while True:
        if was_killed():
            return None

        if os.path.exists(response_path):
            try:
                with open(response_path, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        time.sleep(0.5)


def format_qa_for_prompt(response: dict[str, Any]) -> str:
    """Format a question response dict as markdown for prompt appending."""
    lines = ["### Questions and Answers", ""]
    for answer in response.get("answers", []):
        q = answer.get("question", "")
        selected = answer.get("selected", "")
        custom = answer.get("custom_feedback")
        line = f"**Q: {q}** A: Selected '{selected}'"
        if custom:
            line += f' Custom note: "{custom}"'
        lines.append(line)
        lines.append("")
    global_note = response.get("global_note")
    if global_note:
        lines.append(f"**Global note from user:** {global_note}")
        lines.append("")
    return "\n".join(lines)
