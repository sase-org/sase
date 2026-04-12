"""Remote sync operations for the memory store."""

from __future__ import annotations

from pathlib import Path

from sase.memory.repo import get_repo_path, run_git


class SyncConflictError(Exception):
    """Raised when sync encounters merge conflicts that need manual resolution."""

    def __init__(self, conflicted_files: list[str]) -> None:
        self.conflicted_files = conflicted_files
        files = ", ".join(conflicted_files)
        super().__init__(
            f"Merge conflicts in: {files}\n"
            "Resolve conflicts in ~/.sase/memory/ then run:\n"
            "  cd ~/.sase/memory && git add -A && git commit"
        )


def add_remote(url: str, name: str = "origin") -> None:
    """Configure a remote for the memory repo."""
    repo = _ensure_repo_initialized()
    existing = _list_remotes(repo)
    if name in existing:
        run_git(repo, "remote", "set-url", name, url)
    else:
        run_git(repo, "remote", "add", name, url)


def remove_remote(name: str = "origin") -> None:
    """Remove a remote from the memory repo."""
    repo = _ensure_repo_initialized()
    existing = _list_remotes(repo)
    if name not in existing:
        raise ValueError(f"Remote '{name}' not configured")
    run_git(repo, "remote", "remove", name)


def get_remote_url(name: str = "origin") -> str | None:
    """Return the URL of the named remote, or None if not configured."""
    repo = _ensure_repo_initialized()
    existing = _list_remotes(repo)
    if name not in existing:
        return None
    result = run_git(repo, "remote", "get-url", name)
    return result.stdout.strip()


def sync(remote: str = "origin") -> str:
    """Pull (rebase) from remote then push.

    Returns a status message describing what happened.
    """
    repo = _ensure_repo_initialized()

    # Verify remote exists
    existing = _list_remotes(repo)
    if remote not in existing:
        raise ValueError(
            f"Remote '{remote}' not configured. Run: sase memory remote add <url>"
        )

    # Determine current branch
    branch = _current_branch(repo)

    # Fetch first so we know remote state
    run_git(repo, "fetch", remote)

    # Check if remote branch exists
    remote_branch = f"{remote}/{branch}"
    has_remote_branch = _ref_exists(repo, remote_branch)

    if not has_remote_branch:
        # First push — no remote branch yet
        run_git(repo, "push", "-u", remote, branch)
        return f"Pushed {branch} to {remote} (first sync)"

    # Pull with rebase
    try:
        run_git(repo, "rebase", remote_branch)
    except RuntimeError as exc:
        # Check for conflicts
        conflicted = _conflicted_files(repo)
        if conflicted:
            run_git(repo, "rebase", "--abort")
            raise SyncConflictError(conflicted) from exc
        raise

    # Push
    run_git(repo, "push", remote, branch)
    return f"Synced {branch} with {remote}"


def _ensure_repo_initialized() -> Path:
    """Return the repo path, raising if not initialized."""
    repo = get_repo_path()
    if not (repo / ".git").is_dir():
        raise RuntimeError("Memory repo not initialized. Run: sase memory init")
    return repo


def _list_remotes(repo: Path) -> dict[str, str]:
    """Return {name: url} for all configured remotes."""
    result = run_git(repo, "remote", "-v")
    remotes: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2 and "(fetch)" in line:
            remotes[parts[0]] = parts[1]
    return remotes


def _current_branch(repo: Path) -> str:
    """Return the name of the current branch."""
    result = run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return result.stdout.strip()


def _ref_exists(repo: Path, ref: str) -> bool:
    """Check if a git ref exists."""
    import subprocess

    result = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _conflicted_files(repo: Path) -> list[str]:
    """Return list of files with merge conflicts."""
    import subprocess

    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=U"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [f for f in result.stdout.strip().splitlines() if f]
