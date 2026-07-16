"""Question flow and Q&A prompt helpers for the agent runner."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sase.axe.runner_signals import was_killed
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
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

    session_id = str(uuid.uuid4())
    agent_cl_name = os.environ.get("SASE_AGENT_CL_NAME")
    agent_project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    agent_timestamp = os.environ.get("SASE_AGENT_TIMESTAMP")
    agent_root_timestamp = os.environ.get("SASE_AGENT_ROOT_TIMESTAMP")
    action_data = {
        key: value
        for key, value in {
            "session_id": session_id,
            "agent_cl_name": agent_cl_name,
            "agent_project_file": agent_project_file,
            "agent_timestamp": agent_timestamp,
            "agent_root_timestamp": agent_root_timestamp,
        }.items()
        if value
    }

    from sase.user_question_actions import create_user_question_gate

    gate = create_user_question_gate(
        questions,
        session_id=session_id,
        producer={
            "agent": os.environ.get("SASE_AGENT"),
            "artifacts_dir": artifacts_dir,
            **action_data,
        },
        action_data=action_data,
        auto=is_auto_approve_active(),
    )
    request_path = str(gate.request_path)
    response_path = str(gate.response_path)

    if gate.notification_id is None:
        from sase.notification_gates.poller import poll_gate

        terminal = poll_gate(gate.bundle_path)
        if terminal is None or terminal.status != "responded":
            return None
        return _question_result(
            terminal.payload,
            request_path=request_path,
            response_path=response_path,
            session_id=session_id,
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

    try:
        from sase.notification_gates.poller import wait_for_gate

        terminal = wait_for_gate(
            gate.bundle_path,
            poll_interval=0.2,
            cancelled=was_killed,
        )
        if terminal.status != "responded":
            return None
        response = _question_result(
            terminal.payload,
            request_path=request_path,
            response_path=response_path,
            session_id=session_id,
        )
        if marker_written and reacquire_runner_slot is not None:
            reacquire_runner_slot(
                lambda: _remove_pending_question_marker(
                    artifacts_dir,
                    claimed_at=run_started_at,
                    strict=True,
                )
            )
        return response
    finally:
        _remove_pending_question_marker(artifacts_dir)


def _question_result(
    response: dict[str, Any],
    *,
    request_path: str,
    response_path: str,
    session_id: str,
) -> dict[str, Any]:
    """Translate a neutral gate response into legacy continuation data."""
    result = response.get("result")
    if not isinstance(result, dict):
        raise ValueError("question gate response is missing its result")
    translated = dict(result)
    translated["_question_request_path"] = request_path
    translated["_question_response_path"] = response_path
    translated["_question_session_id"] = session_id
    return translated
