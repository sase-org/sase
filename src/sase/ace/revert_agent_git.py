"""Git subprocess helpers for Agents-tab commit reverts."""

from __future__ import annotations

import subprocess

from sase.git_lock_retry import run_with_git_lock_retry

_GIT_TIMEOUT_SECONDS = 60


def run_git(
    workspace_dir: str,
    args: list[str],
    *,
    timeout: int = _GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    try:
        result, _outcome = run_with_git_lock_retry(
            lambda: subprocess.run(
                ["git", "-C", workspace_dir, *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            ),
            cwd=workspace_dir,
        )
        return result
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(
            args, returncode=1, stdout="", stderr=str(exc)
        )


def is_git_worktree(workspace_dir: str) -> bool:
    out = run_git(workspace_dir, ["rev-parse", "--is-inside-work-tree"])
    return out.returncode == 0 and out.stdout.strip() == "true"


def worktree_is_clean(workspace_dir: str) -> bool | None:
    out = run_git(workspace_dir, ["status", "--porcelain"])
    if out.returncode != 0:
        return None
    return out.stdout.strip() == ""


def commit_exists(workspace_dir: str, sha: str) -> bool:
    out = run_git(workspace_dir, ["cat-file", "-e", f"{sha}^{{commit}}"])
    return out.returncode == 0


def current_head(workspace_dir: str) -> str | None:
    out = run_git(workspace_dir, ["rev-parse", "HEAD"])
    if out.returncode != 0:
        return None
    sha = out.stdout.strip()
    return sha or None


def commit_subject(workspace_dir: str, sha: str) -> str:
    out = run_git(workspace_dir, ["log", "-1", "--format=%s", sha])
    return out.stdout.strip() if out.returncode == 0 else ""


__all__ = [
    "commit_exists",
    "commit_subject",
    "current_head",
    "is_git_worktree",
    "run_git",
    "worktree_is_clean",
]
