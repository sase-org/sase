"""Local convergence diagnostics for bead-store repositories."""

from __future__ import annotations

from collections.abc import Callable
import subprocess
from pathlib import Path

from sase.bead._sync_git import (
    find_git_root as _find_git_root,
    relative_pathspec as _relative_pathspec,
)
from sase.bead._sync_logs import (
    latest_bead_sync_log,
    managed_sync_log_diagnostics,
)


_DEEP_DIVERGENCE_SIDE_THRESHOLD = 3


def bead_sync_diagnostics(
    beads_dir: Path,
    *,
    find_git_root: Callable[[Path], Path | None] = _find_git_root,
) -> list[str]:
    """Report convergence problems visible from the local clone."""
    repo_root = find_git_root(beads_dir)
    if repo_root is None:
        return []
    messages: list[str] = []
    git_dir = _git_state_path(repo_root, "")
    if (git_dir / "rebase-merge").is_dir() or (git_dir / "rebase-apply").is_dir():
        messages.append("WARNING: bead store is mid-rebase")

    counts = subprocess.run(
        ["git", "rev-list", "--left-right", "--count", "@{upstream}...HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if counts.returncode == 0:
        try:
            behind, ahead = (int(value) for value in counts.stdout.split())
        except (TypeError, ValueError):
            behind = ahead = 0
        if behind and ahead:
            messages.append(
                f"WARNING: bead store has diverged ({ahead} local, {behind} remote commits)"
            )
            if max(ahead, behind) >= _DEEP_DIVERGENCE_SIDE_THRESHOLD:
                messages.append(
                    "WARNING: bead store divergence is deep "
                    f"({ahead} local, {behind} remote commits)"
                )
        elif ahead:
            messages.append(f"WARNING: bead store has {ahead} unpushed commit(s)")
        elif behind:
            messages.append(f"WARNING: bead store is {behind} commit(s) behind")
        if ahead:
            bead_commits = unpushed_bead_commit_count(repo_root, beads_dir)
            if bead_commits:
                messages.append(
                    "WARNING: bead store has "
                    f"{bead_commits} unpushed local bead commit(s)"
                )

    from sase.sdd._repository_recovery_reaper import (
        RECOVERY_REF_PREFIX,
        RECOVERY_STASH_SUBJECT_FRAGMENT,
    )

    recovery_refs = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname)", RECOVERY_REF_PREFIX],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if recovery_refs.returncode == 0:
        ref_count = len(
            [line for line in recovery_refs.stdout.splitlines() if line.strip()]
        )
        if ref_count:
            messages.append(f"WARNING: bead store retains {ref_count} recovery ref(s)")

    recovery_stashes = subprocess.run(
        ["git", "stash", "list", "--format=%gs"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if recovery_stashes.returncode == 0:
        stash_count = sum(
            RECOVERY_STASH_SUBJECT_FRAGMENT in subject
            for subject in recovery_stashes.stdout.splitlines()
        )
        if stash_count:
            messages.append(
                f"WARNING: bead store retains {stash_count} recovery stash(es)"
            )

    messages.extend(managed_sync_log_diagnostics(repo_root))

    if messages:
        latest = latest_bead_sync_log()
        if latest is not None:
            messages.append(f"INFO: latest bead sync log: {latest}")
    return messages


def unpushed_bead_commit_count(repo_root: Path, beads_dir: Path) -> int:
    """Count local-only commits that touch canonical bead state."""
    try:
        rel_beads = _relative_pathspec(beads_dir, repo_root)
    except ValueError:
        return 0
    result = subprocess.run(
        [
            "git",
            "rev-list",
            "--count",
            "@{upstream}..HEAD",
            "--",
            f"{rel_beads}/",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def _git_state_path(repo_root: Path, name: str) -> Path:
    """Compatibility wrapper for resolving files in a checkout's Git dir."""
    from sase.sdd._integration_marker import git_state_path

    return git_state_path(repo_root, name)
