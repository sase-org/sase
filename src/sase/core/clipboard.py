"""System clipboard utilities."""

from __future__ import annotations

import os
import subprocess
import sys


def _clipboard_commands() -> list[list[str]]:
    """Return candidate clipboard commands for the current platform."""
    if sys.platform == "darwin":
        return [["pbcopy"]]
    if sys.platform.startswith("linux"):
        wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        x11 = bool(os.environ.get("DISPLAY"))
        if not wayland and not x11:
            return [
                ["wl-copy"],
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
            ]
        commands: list[list[str]] = []
        if wayland:
            commands.append(["wl-copy"])
        if x11:
            commands.append(["xclip", "-selection", "clipboard"])
            commands.append(["xsel", "--clipboard", "--input"])
        return commands
    return []


def copy_to_system_clipboard(content: str) -> bool:
    """Copy content to the system clipboard."""
    for clipboard_cmd in _clipboard_commands():
        try:
            subprocess.run(
                clipboard_cmd,
                input=content,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return False
