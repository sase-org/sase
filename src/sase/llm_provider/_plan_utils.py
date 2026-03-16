"""Shared plan utilities for LLM providers."""

import json
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Poll interval for plan approval responses (seconds)
_POLL_INTERVAL = 0.5


@dataclass
class PlanApprovalResult:
    """Result from plan approval flow."""

    action: str  # "approve" or "epic"
    plan_file: str


def save_plan_to_sase(plan_file: str) -> Path:
    """Copy a plan file to ``~/.sase/plans/`` for persistence."""
    sase_plans_dir = Path.home() / ".sase" / "plans"
    sase_plans_dir.mkdir(parents=True, exist_ok=True)
    src = Path(plan_file)
    # Strip "sase_plan_" prefix if present
    name = src.name
    if name.startswith("sase_plan_"):
        name = name[len("sase_plan_") :]
    dest = sase_plans_dir / name
    if dest.exists():
        dest_path = Path(name)
        stem = dest_path.stem
        suffix = dest_path.suffix
        counter = 1
        while dest.exists():
            dest = sase_plans_dir / f"{stem}_{counter}{suffix}"
            counter += 1
    shutil.copy2(src, dest)
    return dest


def handle_plan_approval(
    plan_file: str | None,
    session_id: str,
    *,
    killed_check: Callable[[], bool] | None = None,
    epic_available: bool = False,
) -> PlanApprovalResult | None:
    """Handle plan approval flow.

    Creates a TUI notification via ``notify_plan_approval()``, then polls for
    the user's response.  Sends desktop notification and tmux bell.

    Args:
        plan_file: Path to the plan file.
        session_id: Unique session ID for the approval flow.
        killed_check: Optional callable that returns True if the process was
            killed (SIGTERM). When provided, the poll loop checks it each
            iteration and returns None early if killed.
        epic_available: Whether the Epic option should be offered.

    Returns a ``PlanApprovalResult`` when accepted, or ``None`` if
    rejected / missing / killed.
    """
    from sase.main.plan_approve_handler import is_auto_approve_active

    if is_auto_approve_active():
        return (
            PlanApprovalResult(action="approve", plan_file=plan_file)
            if plan_file
            else None
        )

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
        epic_available=epic_available,
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

                action = response_data.get("action")
                if action in ("approve", "epic"):
                    response_path.unlink()
                    assert plan_file is not None
                    return PlanApprovalResult(action=action, plan_file=plan_file)
                # On rejection, do NOT delete response_path so
                # read_plan_feedback() can read the feedback.
                return None
            except (json.JSONDecodeError, OSError):
                pass

        time.sleep(_POLL_INTERVAL)
