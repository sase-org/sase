"""System clipboard utilities."""

from __future__ import annotations

import subprocess
import sys


def _clipboard_commands() -> list[list[str]]:
    """Return candidate clipboard commands for the current platform."""
    if sys.platform == "darwin":
        return [["pbcopy"]]
    if sys.platform.startswith("linux"):
        return [
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]
    return []


def copy_to_system_clipboard(content: str) -> bool:
    """Copy content to the system clipboard."""
    for clipboard_cmd in _clipboard_commands():
        try:
            subprocess.run(clipboard_cmd, input=content, text=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return False
