"""Helper utilities for the agent runner.

Pure utility functions for workflow state extraction, marker files,
follow-up artifacts, and question flows.
"""

import json
import os
import time
import uuid
from typing import Any

from sase.axe_runner_utils import was_killed
from sase.shared_utils import create_artifacts_directory


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

    # Extract diff_path: last step's first path-typed output
    diff_path: str | None = None
    steps_list = data.get("steps", [])
    if steps_list:
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

    # Fallback: check for literal diff_path key in last step
    if not diff_path and steps_list:
        last_out = steps_list[-1].get("output")
        if isinstance(last_out, dict) and last_out.get("diff_path"):
            diff_path = str(last_out["diff_path"])

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


def create_followup_artifacts(
    project_name: str,
    base_meta: dict[str, Any],
    suffix: str,
    prev_artifacts_timestamp: str,
    *,
    workspace_num: int | None = None,
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
