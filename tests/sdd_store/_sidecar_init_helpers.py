from __future__ import annotations

from pathlib import Path
import subprocess

import pytest


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def bare_remote(tmp_path: Path, name: str) -> Path:
    remote = tmp_path / f"{name}.git"
    remote.mkdir()
    git(remote, "init", "--bare")
    return remote


def configure_git_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.sdd._sidecar_init.get_primary_workspace_dir",
        lambda workspace, _workspace_num: workspace,
    )
    for key, value in {
        "GIT_AUTHOR_EMAIL": "sase@example.test",
        "GIT_AUTHOR_NAME": "SASE Tests",
        "GIT_COMMITTER_EMAIL": "sase@example.test",
        "GIT_COMMITTER_NAME": "SASE Tests",
    }.items():
        monkeypatch.setenv(key, value)
