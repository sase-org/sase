"""Question flow and Q&A prompt helpers for the agent runner."""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sase.axe.runner_utils import was_killed
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)

if TYPE_CHECKING:
    from sase.main.qa_markdown import QARound


def handle_questions_flow(
    questions: list[dict[str, Any]], artifacts_dir: str
) -> dict[str, Any] | None:
    """Handle the questions notification and polling flow."""
    from sase.main.plan_approve_handler import (
        get_tmux_prefix,
        is_auto_approve_active,
        ring_tmux_bell,
        send_desktop_notification,
    )

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
    """Build a QARound from a question list and response dict."""
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
    """Render accumulated Q&A rounds as a single prompt-bound section."""
    from sase.main.qa_markdown import build_merged_qa_markdown

    body = build_merged_qa_markdown(rounds)
    return f"%xprompts_enabled:false\n{body}\n%xprompts_enabled:true"
