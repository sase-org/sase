"""Clone, identity, and git helpers for agents sidecar synchronization."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from sase.agents_sync._git_sync_ops_lock import bounded_agents_lock
from sase.agents_sync.git import GitRunner
from sase.agents_sync.models import ProjectTarget
from sase.config import require_agent_owner_identity
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.sdd._push_race import is_retryable_push_race


def ensure_agents_clone(
    target: ProjectTarget,
    *,
    git_runner: GitRunner,
    lock_timeout_seconds: float,
) -> str | None:
    if (target.sidecar_path / ".git").exists():
        return None
    target.sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    clone_lock = target.sidecar_path.parent / ".sase-agents-sync-clone.lock"
    with bounded_agents_lock(clone_lock, lock_timeout_seconds) as acquired:
        if not acquired:
            return "agents sync clone lock is busy"
        if (target.sidecar_path / ".git").exists():
            return None
        if target.sidecar_path.exists():
            return f"agents sidecar path is not a git clone: {target.sidecar_path}"
        temp_root = Path(
            tempfile.mkdtemp(
                prefix=".sase-agents-clone-", dir=target.sidecar_path.parent
            )
        )
        checkout = temp_root / "checkout"
        try:
            cloned = git_runner(
                target.sidecar_path.parent,
                ["clone", "--origin", "origin", target.remote_url, str(checkout)],
                network=True,
                op="agents_sync.clone",
            )
            if cloned.returncode != 0:
                return agents_git_error(
                    "could not clone configured agents sidecar", cloned
                )
            os.replace(checkout, target.sidecar_path)
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)
    return None


def coerce_owner(owner: AgentOwnerIdentity | str) -> AgentOwnerIdentity:
    if isinstance(owner, AgentOwnerIdentity):
        return owner
    try:
        configured = require_agent_owner_identity()
    except (RuntimeError, ValueError):
        # Compatibility for direct internal/test calls that historically
        # supplied only the machine. Public sync always requires full identity.
        return AgentOwnerIdentity("local", owner)
    return (
        configured
        if configured.machine_name == owner
        else AgentOwnerIdentity(configured.username, owner)
    )


def pull_agents_rebase(
    repo: Path, git_runner: GitRunner, op: str
) -> subprocess.CompletedProcess[str]:
    return git_runner(
        repo,
        ["pull", "--rebase", "--no-autostash"],
        network=True,
        op=op,
    )


def abort_agents_rebase(repo: Path, git_runner: GitRunner) -> str | None:
    git_dir = agents_git_dir(repo, git_runner)
    if not any(
        (git_dir / marker).exists() for marker in ("rebase-merge", "rebase-apply")
    ):
        return None
    result = git_runner(
        repo,
        ["rebase", "--abort"],
        op="agents_sync.rebase_abort",
    )
    return (
        None
        if result.returncode == 0
        else agents_git_error("git rebase --abort failed", result)
    )


def agents_git_dir(repo: Path, git_runner: GitRunner) -> Path:
    result = git_runner(
        repo,
        ["rev-parse", "--git-dir"],
        op="agents_sync.git_dir",
    )
    if result.returncode != 0 or not result.stdout.strip():
        return repo / ".git"
    git_dir = Path(result.stdout.strip())
    return git_dir if git_dir.is_absolute() else repo / git_dir


def agents_ahead_count(repo: Path, git_runner: GitRunner) -> int:
    result = git_runner(
        repo,
        ["rev-list", "--count", "@{upstream}..HEAD"],
        op="agents_sync.ahead",
    )
    try:
        return int(result.stdout.strip()) if result.returncode == 0 else 0
    except ValueError:
        return 0


def is_agents_non_fast_forward(result: subprocess.CompletedProcess[str]) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    return "[rejected]" in text or is_retryable_push_race(result.stdout, result.stderr)


def agents_git_error(
    prefix: str,
    result: subprocess.CompletedProcess[str],
    cleanup: str | None = None,
) -> str:
    detail = (result.stderr or result.stdout or "unknown git error").strip()
    message = f"{prefix}: {detail}"
    return f"{message}; {cleanup}" if cleanup else message
