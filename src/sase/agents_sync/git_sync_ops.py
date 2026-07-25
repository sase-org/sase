"""Low-level Git and locking operations for agents sidecar synchronization."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from sase.agents_sync.git import GitRunner
from sase.agents_sync.models import ProjectTarget
from sase.config import require_agent_owner_identity
from sase.core.agent_identity_facade import AgentOwnerIdentity

DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_TIMEOUT_ENV = "SASE_AGENTS_SYNC_LOCK_TIMEOUT"
_AGENTS_PAYLOAD_PATHS = (
    "README.md",
    "schema.json",
    "users",
    "agents",
    "families",
)


def commit_agents_payload_if_dirty(
    repo: Path,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
) -> bool | str:
    staged = git_runner(
        repo,
        ["add", "--force", "--", *_AGENTS_PAYLOAD_PATHS],
        op="agents_sync.stage",
    )
    if staged.returncode != 0:
        return agents_git_error("could not stage agents sidecar payload", staged)
    dirty = git_runner(
        repo,
        ["diff", "--cached", "--quiet", "--", *_AGENTS_PAYLOAD_PATHS],
        op="agents_sync.diff_staged",
    )
    if dirty.returncode == 0:
        return False
    if dirty.returncode != 1:
        return agents_git_error(
            "could not inspect staged agents sidecar changes",
            dirty,
        )
    committed = git_runner(
        repo,
        [
            "-c",
            "user.name=SASE",
            "-c",
            "user.email=sase@localhost",
            "commit",
            "-m",
            f"chore(agents): sync from {owner.username}.{owner.machine_name}",
        ],
        op="agents_sync.commit",
    )
    if committed.returncode != 0:
        return agents_git_error("could not commit agents sidecar payload", committed)
    return True


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


@contextmanager
def bounded_agents_lock(path: Path, timeout_seconds: float) -> Iterator[bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    try:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(0.05, max(deadline - time.monotonic(), 0.0)))
        yield acquired
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def is_agents_non_fast_forward(result: subprocess.CompletedProcess[str]) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    return "non-fast-forward" in text or "fetch first" in text or "[rejected]" in text


def agents_git_error(
    prefix: str,
    result: subprocess.CompletedProcess[str],
    cleanup: str | None = None,
) -> str:
    detail = (result.stderr or result.stdout or "unknown git error").strip()
    message = f"{prefix}: {detail}"
    return f"{message}; {cleanup}" if cleanup else message


def configured_agents_lock_timeout() -> float:
    raw = os.environ.get(_LOCK_TIMEOUT_ENV)
    if raw is None:
        return DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS
    return max(value, 0.0)


__all__ = [
    "DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS",
    "abort_agents_rebase",
    "agents_ahead_count",
    "agents_git_dir",
    "agents_git_error",
    "bounded_agents_lock",
    "coerce_owner",
    "commit_agents_payload_if_dirty",
    "configured_agents_lock_timeout",
    "ensure_agents_clone",
    "is_agents_non_fast_forward",
    "pull_agents_rebase",
]
