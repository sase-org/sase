"""Desktop and tmux notification helpers for plan approval."""

from __future__ import annotations

import os
import subprocess

from sase.env_contracts import provider_project_dir_from_env

__all__ = ["get_tmux_prefix", "send_desktop_notification"]


def get_tmux_prefix() -> str:
    """Get the tmux window prefix for notifications."""
    project_dir = provider_project_dir_from_env() or "."
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
