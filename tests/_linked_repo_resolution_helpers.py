"""Shared setup helpers for linked repository resolution tests."""

from __future__ import annotations

from pathlib import Path
import subprocess

from tests.sdd_store._helpers import init_git_identity


def _project_file(path: Path, primary_workspace_dir: Path) -> Path:
    path.write_text(f"WORKSPACE_DIR: {primary_workspace_dir}\nNAME: main\n")
    return path


def _set_github_origin(path: Path, remote: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    # Repositories that create commits own a local, non-signing identity so
    # developer and CI Git configuration cannot change the test outcome.
    init_git_identity(path)
    subprocess.run(
        ["git", "remote", "add", "origin", remote],
        cwd=path,
        check=True,
    )
