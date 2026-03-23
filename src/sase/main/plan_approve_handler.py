"""Utility functions for plan approval and notification support.

Provides helpers for auto-approve checking, desktop notifications,
and tmux bell ringing. Used by the agent runner and other plan/question
orchestration code.
"""

import json
import os
import subprocess
from pathlib import Path

from sase.core.shell import get_vendored_tool


def is_auto_approve_active() -> bool:
    """Check if auto-approve is active via env var or agent_meta.json.

    Returns True if SASE_AGENT_AUTO_APPROVE env var is set, or if the
    ``approve`` field is truthy in the agent's ``agent_meta.json`` (located
    via SASE_ARTIFACTS_DIR).
    """
    if os.environ.get("SASE_AGENT_AUTO_APPROVE"):
        return True

    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if artifacts_dir:
        meta_path = Path(artifacts_dir) / "agent_meta.json"
        try:
            with open(meta_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("approve"):
                return True
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

    return False


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
                [get_vendored_tool("tmux_ring_bell"), tmux_pane],
                check=False,
                capture_output=True,
            )
        except FileNotFoundError:
            pass
