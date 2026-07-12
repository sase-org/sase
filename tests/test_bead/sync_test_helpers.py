"""Shared Git helpers for bead synchronization tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


def configure_git_identity(path: Path) -> None:
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=path,
        capture_output=True,
        check=True,
    )


def init_git_repo(path: Path) -> None:
    """Initialize a Git repository with an initial commit."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    configure_git_identity(path)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=path,
        capture_output=True,
        check=True,
    )
