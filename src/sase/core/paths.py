"""Path and directory utilities."""

import os
import re
from pathlib import Path


def get_sase_tmpdir() -> str | None:
    """Return the SASE temp directory if $SASE_TMPDIR is set, else None.

    When $SASE_TMPDIR is set, the directory is created if it doesn't exist.
    Returning None lets tempfile functions fall back to the system default.
    """
    sase_tmpdir = os.environ.get("SASE_TMPDIR")
    if sase_tmpdir:
        os.makedirs(sase_tmpdir, exist_ok=True)
        return sase_tmpdir
    return None


def get_sase_directory(subdir: str) -> str:
    """Get the path to a subdirectory under ~/.sase/.

    Args:
        subdir: The subdirectory name (e.g., "hooks", "diffs", "chats")

    Returns:
        Full path like "/home/user/.sase/hooks"
    """
    return os.path.expanduser(f"~/.sase/{subdir}")


def ensure_sase_directory(subdir: str) -> str:
    """Ensure a ~/.sase subdirectory exists and return its path.

    Args:
        subdir: The subdirectory name (e.g., "hooks", "diffs", "chats")

    Returns:
        Full path to the created/existing directory
    """
    dir_path = get_sase_directory(subdir)
    Path(dir_path).mkdir(parents=True, exist_ok=True)
    return dir_path


def shorten_path(path: str) -> str:
    """Shorten a file path by replacing home directory with ~.

    Args:
        path: Full file path

    Returns:
        Path with home directory replaced by ~
    """
    return path.replace(str(Path.home()), "~")


def make_safe_filename(name: str) -> str:
    """Convert a string to a safe filename by replacing non-alphanumeric chars.

    Args:
        name: The string to convert

    Returns:
        Safe filename with only alphanumeric chars and underscores
    """
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)
