"""Shared non-interactive Git command runner for rescue modules."""

from __future__ import annotations

import subprocess
from pathlib import Path

RESCUE_GIT_TIMEOUT_SECONDS = 60


def run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    from sase.workspace_provider._utils_git import non_interactive_git_env

    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
            timeout=RESCUE_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(
            ["git", *args],
            returncode=124,
            stdout="",
            stderr=str(exc),
        )
