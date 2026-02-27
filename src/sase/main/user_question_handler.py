"""Handler for the 'sase user-question' CLI subcommand.

Reads hook JSON from stdin, creates a sase notification, writes a request file,
and polls for a response file written by the TUI's UserQuestionModal.
Exit codes: 0 = non-agent fallback, 2 = deny with answers.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import NoReturn

from sase.main.plan_approve_handler import (
    is_auto_approve_active,
    emit_hook_decision,
    get_tmux_prefix,
    ring_tmux_bell,
    send_desktop_notification,
)

# Poll interval for question response (seconds)
_POLL_INTERVAL = 0.5


def _format_answers(response_data: dict) -> str:
    """Format question response data into a human-readable string for Claude.

    Args:
        response_data: Dict with 'answers' list and optional 'global_note'.
            Each answer has 'question', 'selected' list, and optional 'custom_feedback'.

    Returns:
        Formatted string describing the user's answers.
    """
    lines = ["USER ANSWERS PROVIDED VIA SASE TUI", ""]

    for answer in response_data.get("answers", []):
        question = answer.get("question", "")
        selected = answer.get("selected", [])
        custom_feedback = answer.get("custom_feedback", "")

        lines.append(f'Question: "{question}"')
        if selected:
            lines.append(f"Selected: {', '.join(repr(s) for s in selected)}")
        if custom_feedback:
            lines.append(f"Custom feedback: {custom_feedback}")
        lines.append("")

    global_note = response_data.get("global_note", "")
    if global_note:
        lines.append(f"Global note: {global_note}")
        lines.append("")

    lines.append("The user answered via the SASE TUI. Proceed with these selections.")
    return "\n".join(lines)


def handle_user_question_command() -> NoReturn:
    """Handle the user-question subcommand.

    Reads JSON from stdin, creates a notification, writes a request file,
    and polls for a response. Only activates the TUI flow for agents launched
    by sase (SASE_AGENT=1); otherwise falls back to desktop notification + exit 0.
    """
    # Read JSON from stdin
    data: dict = {}
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                print("Error: invalid JSON on stdin", file=sys.stderr)
                sys.exit(1)

    session_id = data.get("session_id", "unknown")
    tool_input = data.get("tool_input", {})
    questions = tool_input.get("questions", [])

    # If not launched by sase, just notify and allow
    if not os.environ.get("SASE_AGENT"):
        prefix = get_tmux_prefix()
        send_desktop_notification(
            f"{prefix} User Question",
            "Claude is asking a question - check your terminal",
        )
        ring_tmux_bell()
        sys.exit(0)

    # Auto-select first option when %approve directive is active
    if is_auto_approve_active():
        answers = []
        for q in questions:
            question_text = q.get("question", "")
            options = q.get("options", [])
            selected = [options[0].get("label", "")] if options else []
            answers.append({"question": question_text, "selected": selected})
        formatted = _format_answers({"answers": answers})
        emit_hook_decision("deny", formatted)
        sys.exit(2)

    # Set up response directory
    response_dir = Path.home() / ".sase" / "user_question" / session_id
    response_dir.mkdir(parents=True, exist_ok=True)

    request_path = response_dir / "question_request.json"
    response_path = response_dir / "question_response.json"

    # Clean stale response file
    if response_path.exists():
        response_path.unlink()

    # Write request file
    request_data = {
        "session_id": session_id,
        "timestamp": time.time(),
        "questions": questions,
    }
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump(request_data, f, indent=2)

    # Create sase notification
    from sase.notifications.senders import notify_user_question

    # Use first question text as notification note (truncated)
    first_question = ""
    if questions:
        first_question = questions[0].get("question", "")
    if len(first_question) > 80:
        first_question = first_question[:77] + "..."

    agent_cl_name = os.environ.get("SASE_AGENT_CL_NAME")
    agent_project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    agent_timestamp = os.environ.get("SASE_AGENT_TIMESTAMP")
    notify_user_question(
        response_dir=str(response_dir),
        session_id=session_id,
        notes=first_question,
        agent_cl_name=agent_cl_name,
        agent_project_file=agent_project_file,
        agent_timestamp=agent_timestamp,
    )

    # Send desktop notification + tmux bell
    prefix = get_tmux_prefix()
    send_desktop_notification(
        f"{prefix} User Question",
        first_question or "Claude is asking a question",
    )
    ring_tmux_bell()

    # Poll for response file (no timeout — wait until the user acts)
    while True:
        if response_path.exists():
            try:
                with open(response_path, encoding="utf-8") as f:
                    response_data = json.load(f)

                # Clean up
                if request_path.exists():
                    request_path.unlink()
                response_path.unlink()

                formatted = _format_answers(response_data)
                emit_hook_decision("deny", formatted)
                sys.exit(2)
            except (json.JSONDecodeError, OSError):
                # Response file exists but couldn't be read, wait and retry
                pass

        time.sleep(_POLL_INTERVAL)
