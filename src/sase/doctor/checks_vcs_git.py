"""Git executable and identity checks for ``sase doctor``."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from sase.diagnostics import CheckStatus, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


GIT_TIMEOUT_SECONDS = 1.0
GitResultFn = Callable[..., subprocess.CompletedProcess[str] | None]
GitConfigFn = Callable[[Path, str], str | None]
WhichFn = Callable[[str], str | None]


def check_vcs_git(
    context: DoctorContext,
    *,
    which_fn: WhichFn | None = None,
    git_result_fn: GitResultFn | None = None,
    git_config_fn: GitConfigFn | None = None,
) -> DiagnosticCheck:
    """Check git availability, repo detection, and effective identity."""
    which = which_fn or shutil.which
    run_git = git_result_fn or git_result
    read_config = git_config_fn or git_config

    git_path = which("git")
    if git_path is None:
        return DiagnosticCheck(
            id="vcs.git",
            group="vcs",
            status="ERROR",
            title="Git executable and identity",
            summary="git executable was not found on PATH",
            next_steps=("Install git and ensure it is available on PATH.",),
            data={"git_executable": None},
        )

    repo = run_git(context.cwd, "rev-parse", "--show-toplevel")
    if repo is None or repo.returncode != 0 or not repo.stdout.strip():
        return DiagnosticCheck(
            id="vcs.git",
            group="vcs",
            status="SKIP",
            title="Git executable and identity",
            summary="git is available; current directory is not a git repository",
            data={"git_executable": git_path, "repo_root": None},
        )

    repo_root = Path(repo.stdout.strip())
    user_name = read_config(repo_root, "user.name")
    user_email = read_config(repo_root, "user.email")
    missing = []
    if not user_name:
        missing.append("user.name")
    if not user_email:
        missing.append("user.email")

    status: CheckStatus = "WARN" if missing else "OK"
    summary = (
        f"git repo detected at {repo_root}; identity configured"
        if not missing
        else f"git repo detected; missing {', '.join(missing)}"
    )
    next_steps = []
    if "user.name" in missing:
        next_steps.append('Run `git config user.name "Your Name"` in this repo.')
    if "user.email" in missing:
        next_steps.append('Run `git config user.email "you@example.com"` in this repo.')

    return DiagnosticCheck(
        id="vcs.git",
        group="vcs",
        status=status,
        title="Git executable and identity",
        summary=summary,
        details=(f"repo root: {repo_root}",),
        next_steps=tuple(next_steps),
        data={
            "git_executable": git_path,
            "repo_root": str(repo_root),
            "user_name_configured": bool(user_name),
            "user_email_configured": bool(user_email),
        },
    )


def git_config(repo_root: Path, key: str) -> str | None:
    result = git_result(repo_root, "config", key)
    if result is None or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def git_result(cwd: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None


__all__ = [
    "GIT_TIMEOUT_SECONDS",
    "check_vcs_git",
    "git_config",
    "git_result",
]
