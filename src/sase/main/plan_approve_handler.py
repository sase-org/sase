"""Handler for the 'sase plan-approve' CLI subcommand.

Reads hook JSON from stdin, creates a sase notification, writes a request file,
and polls for a response file written by the TUI's PlanApprovalModal.
On approval, writes a marker file and allows ExitPlanMode so the agent runner
can detect plan approval and resume the session for implementation.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

# Poll interval for plan approval (seconds)
_POLL_INTERVAL = 0.5
# Timeout for plan approval (seconds) - 10 minutes
_TIMEOUT = 600


def emit_hook_decision(decision: str, reason: str = "") -> None:
    """Print Claude Code PreToolUse hook decision JSON to stdout."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output), flush=True)


def _find_plan_file(session_id: str) -> str | None:
    """Find the most recently modified .md plan file for this session.

    Searches ~/.claude/plans/ for the most recently modified markdown file.

    Args:
        session_id: Claude Code session ID (for future per-session filtering).

    Returns:
        Path to the plan file, or None if not found.
    """
    plans_dir = Path.home() / ".claude" / "plans"
    if not plans_dir.is_dir():
        return None

    md_files = list(plans_dir.glob("*.md"))
    if not md_files:
        return None

    # Return the most recently modified file
    return str(max(md_files, key=lambda f: f.stat().st_mtime))


def get_tmux_prefix() -> str:
    """Get the tmux window prefix for notifications."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    project_name = os.path.basename(project_dir)
    prefix = f"[{project_name}]"

    tmux_pane = os.environ.get("TMUX_PANE")
    if tmux_pane:
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-t", tmux_pane, "-p", "#W"],
                capture_output=True,
                text=True,
                check=False,
            )
            window = result.stdout.strip()
            if window:
                prefix = f"[{project_name}#{window}]"
        except FileNotFoundError:
            pass

    return prefix


def send_desktop_notification(title: str, message: str) -> None:
    """Send a desktop notification (cross-platform)."""
    import platform

    if platform.system() == "Darwin":
        subprocess.run(
            ["terminal-notifier", "-title", title, "-message", message],
            check=False,
            capture_output=True,
        )
    else:
        try:
            subprocess.run(
                ["notify-send", title, message],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            pass


def ring_tmux_bell() -> None:
    """Ring the tmux bell for the window running Claude."""
    tmux_pane = os.environ.get("TMUX_PANE")
    if tmux_pane:
        try:
            subprocess.run(
                ["tmux_ring_bell", tmux_pane],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            pass


def handle_plan_approve_command() -> NoReturn:
    """Handle the plan-approve subcommand.

    Reads JSON from stdin, finds the plan file, creates a notification,
    and polls for a response. Only activates the TUI approval flow for
    agents launched by sase (SASE_AGENT=1); otherwise falls back to
    desktop notification + exit 0.
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

    # If not launched by sase, just notify and approve
    if not os.environ.get("SASE_AGENT"):
        prefix = get_tmux_prefix()
        send_desktop_notification(
            f"{prefix} Plan Complete",
            "Planning phase finished - ready for review",
        )
        ring_tmux_bell()
        sys.exit(0)

    # Set up response directory early (needed for marker check)
    response_dir = Path.home() / ".sase" / "plan_approval" / session_id
    response_dir.mkdir(parents=True, exist_ok=True)

    # Idempotency guard: if plan was already approved, skip notification
    marker_path = response_dir / "plan_approved.marker"
    if marker_path.exists():
        emit_hook_decision("allow", "Plan already approved (marker exists)")
        sys.exit(0)

    request_path = response_dir / "plan_request.json"
    response_path = response_dir / "plan_response.json"

    # Only create notification if request doesn't already exist (idempotency)
    if not request_path.exists():
        # Find plan file
        plan_file = _find_plan_file(session_id)
        if not plan_file:
            # No plan file found - still allow approval but without file content
            print("Warning: no plan file found in ~/.claude/plans/", file=sys.stderr)

        # Clean stale response file
        if response_path.exists():
            response_path.unlink()

        # Write request file
        request_data = {
            "plan_file": plan_file,
            "session_id": session_id,
            "timestamp": time.time(),
        }
        with open(request_path, "w", encoding="utf-8") as f:
            json.dump(request_data, f, indent=2)

        # Create sase notification
        from sase.notifications.senders import notify_plan_approval

        project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
        agent_cl_name = os.environ.get("SASE_AGENT_CL_NAME")
        agent_project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
        agent_timestamp = os.environ.get("SASE_AGENT_TIMESTAMP")
        notify_plan_approval(
            plan_file=plan_file or "(no plan file)",
            response_dir=str(response_dir),
            session_id=session_id,
            project_dir=project_dir,
            agent_cl_name=agent_cl_name,
            agent_project_file=agent_project_file,
            agent_timestamp=agent_timestamp,
        )

        # Send desktop notification + tmux bell (preserve existing behavior)
        prefix = get_tmux_prefix()
        send_desktop_notification(
            f"{prefix} Plan Complete", "Plan ready for review in sase ace"
        )
        ring_tmux_bell()
    else:
        # Concurrent/retry invocation — read plan_file from existing request
        try:
            with open(request_path, encoding="utf-8") as f:
                existing_request = json.load(f)
            plan_file = existing_request.get("plan_file")
        except (json.JSONDecodeError, OSError):
            plan_file = None

    # Poll for response file
    start_time = time.time()
    while time.time() - start_time < _TIMEOUT:
        if response_path.exists():
            try:
                with open(response_path, encoding="utf-8") as f:
                    response_data = json.load(f)

                # Clean up
                if request_path.exists():
                    request_path.unlink()
                response_path.unlink()

                action = response_data.get("action", "reject")
                if action == "approve":
                    # Write marker so agent runner knows to resume for implementation
                    marker_path = response_dir / "plan_approved.marker"
                    marker_path.write_text(plan_file or "")

                    emit_hook_decision("allow", "Plan approved by user in sase ace")
                    sys.exit(0)
                else:
                    feedback = response_data.get("feedback", "")
                    reason = feedback if feedback else "Plan rejected by user"
                    emit_hook_decision("deny", reason)
                    sys.exit(2)
            except (json.JSONDecodeError, OSError):
                # Response file exists but couldn't be read, wait and retry
                pass

        time.sleep(_POLL_INTERVAL)

    # Timeout - clean up and reject
    if request_path.exists():
        request_path.unlink()
    emit_hook_decision("deny", "Plan approval timed out")
    sys.exit(2)
