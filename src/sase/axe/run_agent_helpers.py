"""Helper utilities for the agent runner.

Pure utility functions for workflow state extraction, marker files,
follow-up artifacts, and question flows.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.axe.runner_utils import was_killed
from sase.artifacts import create_artifacts_directory
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)

if TYPE_CHECKING:
    from sase.main.qa_markdown import QARound
from sase.plan_chain import (
    AGENT_FAMILY_FIELD,
    AGENT_FAMILY_ROLE_FIELD,
    PLAN_CHAIN_PARENT_TIMESTAMP_FIELD,
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_ROOT_FIELD,
    agent_family_base,
    agent_family_role_for_suffix,
    canonical_plan_chain_suffix,
    is_plan_chain_artifact_meta,
)


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


def read_commit_result_metadata(artifacts_dir: str | None) -> dict[str, str]:
    """Read commit_result.json and return workflow metadata fields."""
    if not artifacts_dir:
        return {}

    commit_result_path = os.path.join(artifacts_dir, "commit_result.json")
    try:
        with open(commit_result_path, encoding="utf-8") as f:
            commit_result = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

    if not isinstance(commit_result, dict):
        return {}

    def _text(value: Any) -> str | None:
        return value if isinstance(value, str) and value else None

    metadata: dict[str, str] = {}
    if message := _text(commit_result.get("message")):
        metadata["meta_commit_message"] = message
    if result := _text(commit_result.get("result")):
        metadata["meta_new_commit"] = result
    if changespec := (
        _text(commit_result.get("changespec_name")) or _text(commit_result.get("name"))
    ):
        metadata["meta_changespec"] = changespec
    if diff_path := _text(commit_result.get("diff_path")):
        metadata["diff_path"] = diff_path
    return metadata


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
    commit_metadata = read_commit_result_metadata(artifacts_dir)
    commit_step_metadata = {
        key: value for key, value in commit_metadata.items() if key != "diff_path"
    }

    state_path = os.path.join(artifacts_dir, "workflow_state.json")
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        commit_diff_path = commit_metadata.get("diff_path")
        if commit_diff_path:
            commit_diff_path = os.path.expanduser(commit_diff_path)
        return commit_step_metadata or None, commit_diff_path

    if not isinstance(data, dict):
        commit_diff_path = commit_metadata.get("diff_path")
        if commit_diff_path:
            commit_diff_path = os.path.expanduser(commit_diff_path)
        return commit_step_metadata or None, commit_diff_path

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

    # commit_result.json is written by the commit workflow and carries the
    # full commit body; workflow text outputs may already be shortened.
    if commit_step_metadata:
        if step_output is None:
            step_output = commit_step_metadata
        else:
            step_output.update(commit_step_metadata)

    # Safety net: extract diff_path from commit_result.json when no workflow
    # step provided one (e.g. hg.yml before it had a dedicated diff step).
    if not diff_path and commit_metadata.get("diff_path"):
        diff_path = commit_metadata["diff_path"]

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


def append_meta_list_field(artifacts_dir: str, key: str, value: Any) -> None:
    """Read agent_meta.json, append *value* to the list at *key*, and write back."""
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        existing = meta.get(key)
        if isinstance(existing, list):
            existing.append(value)
        else:
            meta[key] = [value]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def update_meta_field(artifacts_dir: str, key: str, value: Any) -> None:
    """Read agent_meta.json, set a single key, and write it back."""
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta[key] = value
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def update_meta_suffix(artifacts_dir: str, suffix: str) -> None:
    """Read agent_meta.json, set role_suffix, and write it back."""
    canonical_suffix = canonical_plan_chain_suffix(suffix) or suffix
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["role_suffix"] = canonical_suffix
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def promote_to_workflow(
    artifacts_dir: str,
    base_name: str,
    role_suffix: str = PLAN_CHAIN_PLAN_SUFFIX,
) -> None:
    """Retroactively mark the initial agent as a plan-chain family root.

    Called when the first follow-up agent is created, promoting a
    single-agent run into a multi-agent workflow.  The root keeps the
    user-visible base name; child phases carry suffixed names.
    """
    canonical_suffix = canonical_plan_chain_suffix(role_suffix) or role_suffix
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["name"] = base_name
        meta["workflow_name"] = base_name
        meta[PLAN_CHAIN_ROOT_FIELD] = True
        meta[AGENT_FAMILY_FIELD] = base_name
        meta[AGENT_FAMILY_ROLE_FIELD] = "root"
        meta["role_suffix"] = canonical_suffix
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
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
    index_dirty = False

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
            index_dirty = True

    if not saw_sigterm_failure:
        if index_dirty:
            update_agent_artifact_index_for_marker_mutation(artifacts_dir)
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
            index_dirty = True
        except OSError:
            continue

    if index_dirty:
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)


def update_step_marker_chat_path(artifacts_dir: str, chat_path: str) -> None:
    """Set response_path on step markers missing it after a handoff chat save.

    After ``sase plan``/``sase questions`` SIGTERMs the agent, the step marker
    never gets its ``response_path`` updated.  This backfills it so the TUI can
    display the chat file instead of falling back to raw step_output JSON.

    Skips embedded workflow markers (filenames containing ``__``).
    """
    index_dirty = False
    for marker_path in Path(artifacts_dir).glob("prompt_step_*.json"):
        if "__" in marker_path.name:
            continue
        try:
            with open(marker_path, encoding="utf-8") as f:
                marker_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(marker_data, dict):
            continue
        if marker_data.get("response_path") is not None:
            continue
        marker_data["response_path"] = chat_path
        try:
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump(marker_data, f, indent=2)
            index_dirty = True
        except OSError:
            continue
    if index_dirty:
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)


def create_followup_artifacts(
    project_name: str,
    base_meta: dict[str, Any],
    suffix: str,
    prev_artifacts_timestamp: str,
    *,
    workspace_num: int | None = None,
    agent_name_override: str | None = None,
    workflow_name: str | None = None,
    relationships: dict[str, Any] | None = None,
) -> str:
    """Create a new timestamped artifacts directory for a follow-up agent.

    Inherits metadata fields from the previous agent's meta and adds
    role_suffix and parent_timestamp.

    Returns the new artifacts_dir path.
    """
    from datetime import UTC

    new_artifacts_dir = create_artifacts_directory("ace-run", project_name=project_name)
    canonical_suffix = canonical_plan_chain_suffix(suffix) or suffix

    followup_meta: dict[str, Any] = {"pid": os.getpid()}
    for key in (
        "model",
        "llm_provider",
        "vcs_provider",
        "name",
        "approve",
        "changespec_name",
        "cl_name",
        "bead_id",
    ):
        if base_meta.get(key):
            followup_meta[key] = base_meta[key]
    if agent_name_override is not None:
        followup_meta["name"] = agent_name_override
    if workflow_name is not None:
        followup_meta["workflow_name"] = workflow_name
    followup_meta["role_suffix"] = canonical_suffix
    family_name = (
        workflow_name
        or (
            str(base_meta[AGENT_FAMILY_FIELD])
            if base_meta.get(AGENT_FAMILY_FIELD)
            else None
        )
        or agent_family_base(agent_name_override)
    )
    if family_name:
        followup_meta[AGENT_FAMILY_FIELD] = family_name
    family_role = agent_family_role_for_suffix(canonical_suffix)
    if family_role:
        followup_meta[AGENT_FAMILY_ROLE_FIELD] = family_role
    followup_meta["parent_timestamp"] = prev_artifacts_timestamp
    if is_plan_chain_artifact_meta(followup_meta):
        followup_meta[PLAN_CHAIN_PARENT_TIMESTAMP_FIELD] = prev_artifacts_timestamp
    if workspace_num is not None:
        followup_meta["workspace_num"] = workspace_num
    followup_meta["run_started_at"] = datetime.now(UTC).isoformat()
    if relationships:
        for key, value in relationships.items():
            if value or (isinstance(value, bool) and value is not None):
                followup_meta[key] = value

    with open(
        os.path.join(new_artifacts_dir, "agent_meta.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(followup_meta, f, indent=2)

    # Write initial workflow_state.json so the TUI can merge follow-up agents
    # as WORKFLOW entries immediately, before WorkflowExecutor overwrites it.
    _initial_state: dict[str, object] = {
        "workflow_name": "run",
        "status": "running",
        "current_step_index": 0,
        "steps": [],
        "context": {"cl_name": followup_meta.get("name", "")},
        "artifacts_dir": new_artifacts_dir,
        "pid": os.getpid(),
        "appears_as_agent": True,
    }
    with open(
        os.path.join(new_artifacts_dir, "workflow_state.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(_initial_state, f, indent=2)

    update_agent_artifact_index_for_marker_mutation(new_artifacts_dir)
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
            selected = [options[0]["label"]] if options else []
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
    agent_root_timestamp = os.environ.get("SASE_AGENT_ROOT_TIMESTAMP")
    q_summary = "; ".join(q.get("question", "?") for q in questions[:3])
    notify_user_question(
        response_dir=response_dir,
        session_id=session_id,
        notes=q_summary,
        agent_cl_name=agent_cl_name,
        agent_project_file=agent_project_file,
        agent_timestamp=agent_timestamp,
        agent_root_timestamp=agent_root_timestamp,
    )

    prefix = get_tmux_prefix()
    send_desktop_notification(
        f"{prefix} Agent Question", "Agent has questions in sase ace"
    )
    ring_tmux_bell()

    # Write pending_question.json marker so the TUI can flip status to
    # QUESTION independent of notification dismissed/read state. Cleared
    # on every exit path via try/finally so DONE/FAILED agents never
    # carry a stale marker.
    from datetime import UTC

    pending_marker_path = os.path.join(artifacts_dir, "pending_question.json")
    try:
        marker_payload = {
            "session_id": session_id,
            "request_path": request_path,
            "submitted_at": datetime.now(UTC).isoformat(),
        }
        with open(pending_marker_path, "w", encoding="utf-8") as f:
            json.dump(marker_payload, f, indent=2)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except OSError:
        pass

    # Poll for response
    response_path = os.path.join(response_dir, "question_response.json")
    try:
        while True:
            if was_killed():
                return None

            if os.path.exists(response_path):
                try:
                    with open(response_path, encoding="utf-8") as f:
                        response = json.load(f)
                    if isinstance(response, dict):
                        response["_question_request_path"] = request_path
                        response["_question_response_path"] = response_path
                        response["_question_session_id"] = session_id
                    return response
                except (json.JSONDecodeError, OSError):
                    pass

            time.sleep(0.5)
    finally:
        try:
            os.unlink(pending_marker_path)
            update_agent_artifact_index_for_marker_mutation(artifacts_dir)
        except OSError:
            pass


def build_qa_round(
    questions: list[dict[str, Any]],
    response: dict[str, Any],
) -> QARound:
    """Build a :class:`QARound` from a question list and response dict.

    Pairs questions with answers by index, falling back to
    question-text match if lengths differ (defensive — modal always
    emits one slot per question, but auto-approve / future schema
    drift might not).
    """
    from sase.main.qa_markdown import QARound

    response_answers = response.get("answers", []) or []
    if len(response_answers) == len(questions):
        aligned = list(response_answers)
    else:
        by_text: dict[str, dict[str, Any]] = {
            a.get("question", ""): a for a in response_answers if a.get("question")
        }
        aligned = []
        for q in questions:
            match = by_text.get(q.get("question", ""))
            aligned.append(match if match is not None else {})

    return QARound(
        questions=list(questions),
        answers=aligned,
        global_note=response.get("global_note") or None,
    )


def merge_qa_for_prompt(rounds: list[QARound]) -> str:
    """Render accumulated Q&A rounds as a single prompt-bound section.

    Emits exactly one ``### Questions and Answers`` block wrapped in
    one ``%xprompts_enabled:false`` / ``%xprompts_enabled:true`` pair,
    regardless of round count. See :func:`build_merged_qa_markdown` for
    rendering semantics.
    """
    from sase.main.qa_markdown import build_merged_qa_markdown

    body = build_merged_qa_markdown(rounds)
    return f"%xprompts_enabled:false\n{body}\n%xprompts_enabled:true"
