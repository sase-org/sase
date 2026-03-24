"""Editor utilities for commit message editing."""

import os
import subprocess


def get_editor() -> str:
    """Get the editor to use for commit messages.

    Returns:
        The editor command to use. Checks $EDITOR first, then falls back to
        nvim if available, otherwise vim.
    """
    # Check EDITOR environment variable first
    editor = os.environ.get("EDITOR")
    if editor:
        return editor

    # Fall back to nvim if it exists
    try:
        result = subprocess.run(
            ["which", "nvim"], capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            return "nvim"
    except Exception:
        pass

    # Default to vim
    return "vim"
