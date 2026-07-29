"""System clipboard utilities."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping


def _clipboard_commands() -> list[list[str]]:
    """Return candidate clipboard commands for the current platform."""
    return clipboard_commands()


def clipboard_commands(
    *,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> list[list[str]]:
    """Return candidate clipboard commands for the supplied environment."""
    environment = os.environ if env is None else env
    current_platform = sys.platform if platform is None else platform
    commands: list[list[str]] = []
    if environment.get("TMUX"):
        commands.append(["tmux", "load-buffer", "-w", "-"])

    if current_platform == "darwin":
        return [*commands, ["pbcopy"]]
    if current_platform.startswith("linux"):
        wayland = bool(environment.get("WAYLAND_DISPLAY"))
        x11 = bool(environment.get("DISPLAY"))
        if not wayland and not x11:
            return [
                *commands,
                ["wl-copy"],
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
            ]
        if wayland:
            commands.append(["wl-copy"])
        if x11:
            commands.append(["xclip", "-selection", "clipboard"])
            commands.append(["xsel", "--clipboard", "--input"])
        return commands
    return commands


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


def clipboard_available(
    *,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> bool:
    """Return True when a usable system clipboard command is on PATH."""
    commands = (
        _clipboard_commands()
        if env is None and platform is None
        else clipboard_commands(env=env, platform=platform)
    )
    return any(shutil.which(cmd[0]) is not None for cmd in commands)
