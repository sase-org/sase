"""Shared helpers for commit hook modules."""

from __future__ import annotations

import subprocess


def get_repo_root(cwd: str) -> str:
    """Return the repository root directory, or an empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=cwd,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""
