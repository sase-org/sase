"""Shared plan utilities for LLM providers.

Extracted from gemini.py and claude.py to avoid duplication across providers.
"""

import json
import os
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path

# Poll interval for plan approval responses (seconds)
_POLL_INTERVAL = 0.5


def save_response_as_plan(text: str, provider_name: str) -> str:
    """Save response text as a plan file when no ``.md`` file exists on disk.

    Args:
        text: The plan text to save.
        provider_name: Provider name used to determine directory
            (e.g. ``"gemini"`` -> ``~/.gemini/plans/``).

    Returns:
        Path to the saved plan file.
    """
    plans_dir = Path.home() / f".{provider_name}" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plans_dir / f"{provider_name}_plan_{uuid.uuid4().hex[:8]}.md"
    plan_path.write_text(text, encoding="utf-8")
    return str(plan_path)


def save_plan_to_sase(plan_file: str) -> Path:
    """Copy a plan file to ``~/.sase/plans/`` for persistence."""
    sase_plans_dir = Path.home() / ".sase" / "plans"
    sase_plans_dir.mkdir(parents=True, exist_ok=True)
    src = Path(plan_file)
    dest = sase_plans_dir / src.name
    if dest.exists():
        stem = src.stem
        suffix = src.suffix
        counter = 1
        while dest.exists():
            dest = sase_plans_dir / f"{stem}_{counter}{suffix}"
            counter += 1
    shutil.copy2(src, dest)
    return dest


def write_plan_path_artifact(saved_plan_path: Path) -> None:
    """Write ``plan_path.json`` so agent runner can thread it to ``done.json``."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if artifacts_dir:
        plan_path_file = Path(artifacts_dir) / "plan_path.json"
        plan_path_file.write_text(json.dumps({"plan_path": str(saved_plan_path)}))


def read_plan_feedback(approval_dir: Path) -> str | None:
    """Read plan rejection feedback from plan_response.json if present.

    Returns the feedback string if the plan was rejected with feedback,
    or None otherwise.
    """
    response_path = approval_dir / "plan_response.json"
    if not response_path.exists():
        return None
    try:
        with open(response_path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("action") == "reject" and data.get("feedback"):
            return data["feedback"]
    except (json.JSONDecodeError, OSError):
        pass
    return None


def append_plan_feedback_log(feedback: str, round_num: int) -> None:
    """Append a plan feedback record to plan_feedback.jsonl in SASE_ARTIFACTS_DIR."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return
    record = {
        "round": round_num,
        "feedback": feedback,
        "timestamp": time.time(),
    }
    try:
        path = os.path.join(artifacts_dir, "plan_feedback.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


def handle_plan_approval(
    plan_file: str | None,
    session_id: str,
    *,
    killed_check: Callable[[], bool] | None = None,
) -> str | None:
    """Handle plan approval flow.

    Creates a TUI notification via ``notify_plan_approval()``, then polls for
    the user's response.  Sends desktop notification and tmux bell.

    Args:
        plan_file: Path to the plan file.
        session_id: Unique session ID for the approval flow.
        killed_check: Optional callable that returns True if the process was
            killed (SIGTERM). When provided, the poll loop checks it each
            iteration and returns None early if killed.

    Returns the plan file path if approved, ``None`` if rejected or missing.
    """
    from sase.main.plan_approve_handler import is_auto_approve_active

    if is_auto_approve_active():
        return plan_file

    if not plan_file:
        return None

    response_dir = Path.home() / ".sase" / "plan_approval" / session_id
    response_dir.mkdir(parents=True, exist_ok=True)

    request_path = response_dir / "plan_request.json"
    response_path = response_dir / "plan_response.json"

    if response_path.exists():
        response_path.unlink()

    request_data = {
        "plan_file": plan_file,
        "session_id": session_id,
        "timestamp": time.time(),
    }
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump(request_data, f, indent=2)

    from sase.notifications.senders import notify_plan_approval

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    agent_cl_name = os.environ.get("SASE_AGENT_CL_NAME")
    agent_project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    agent_timestamp = os.environ.get("SASE_AGENT_TIMESTAMP")
    notify_plan_approval(
        plan_file=plan_file,
        response_dir=str(response_dir),
        session_id=session_id,
        project_dir=project_dir,
        agent_cl_name=agent_cl_name,
        agent_project_file=agent_project_file,
        agent_timestamp=agent_timestamp,
    )

    # Desktop notification + tmux bell
    from sase.main.plan_approve_handler import (
        get_tmux_prefix,
        ring_tmux_bell,
        send_desktop_notification,
    )

    prefix = get_tmux_prefix()
    send_desktop_notification(
        f"{prefix} Plan Complete", "Plan ready for review in sase ace"
    )
    ring_tmux_bell()

    # Poll for response (blocks until the user acts)
    while True:
        if killed_check is not None and killed_check():
            return None

        if response_path.exists():
            try:
                with open(response_path, encoding="utf-8") as f:
                    response_data = json.load(f)

                if request_path.exists():
                    request_path.unlink()

                if response_data.get("action") == "approve":
                    response_path.unlink()
                    return plan_file
                # On rejection, do NOT delete response_path so
                # read_plan_feedback() can read the feedback.
                return None
            except (json.JSONDecodeError, OSError):
                pass

        time.sleep(_POLL_INTERVAL)
