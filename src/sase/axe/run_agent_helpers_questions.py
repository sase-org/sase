"""Question flow and Q&A prompt helpers for the agent runner."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sase.axe.runner_signals import was_killed
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.paths import sase_subdir
from sase.main.qa_prompt import build_qa_round, merge_qa_for_prompt

RunnerSlotReacquirer = Callable[[Callable[[], str]], str]


def _remove_pending_question_marker(
    artifacts_dir: str,
    *,
    claimed_at: str | None = None,
    strict: bool = False,
) -> str:
    """Remove the question pause marker and return a slot-claim timestamp."""
    marker_path = os.path.join(artifacts_dir, "pending_question.json")
    try:
        os.unlink(marker_path)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except OSError:
        if strict:
            raise
    return claimed_at or datetime.now(UTC).isoformat()


def handle_questions_flow(
    questions: list[dict[str, Any]],
    artifacts_dir: str,
    *,
    reacquire_runner_slot: RunnerSlotReacquirer | None = None,
    run_started_at: str | None = None,
) -> dict[str, Any] | None:
    """Handle the questions notification, pause, and slot reacquisition flow."""
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
    response_dir = str(sase_subdir("user_question") / session_id)
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
    marker_written = False
    try:
        marker_payload = {
            "session_id": session_id,
            "request_path": request_path,
            "submitted_at": datetime.now(UTC).isoformat(),
        }
        with open(pending_marker_path, "w", encoding="utf-8") as f:
            json.dump(marker_payload, f, indent=2)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
        marker_written = True
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
                    if marker_written and reacquire_runner_slot is not None:
                        reacquire_runner_slot(
                            lambda: _remove_pending_question_marker(
                                artifacts_dir,
                                claimed_at=run_started_at,
                                strict=True,
                            )
                        )
                    return response
                except (json.JSONDecodeError, OSError):
                    pass

            time.sleep(0.5)
    finally:
        _remove_pending_question_marker(artifacts_dir)
