"""Local convergence diagnostics for bead-store repositories."""

from __future__ import annotations

from collections.abc import Callable
import subprocess
from dataclasses import dataclass
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


@dataclass(frozen=True)
class BeadPublicationStatus:
    """Whether a bead store's canonical commits reached its remote."""

    beads_dir: Path
    repo_root: Path | None
    applicable: bool
    has_upstream: bool
    unpushed_commits: int

    @property
    def published(self) -> bool:
        """Whether no canonical bead commit is left to publish."""
        return not self.applicable or self.unpushed_commits == 0


def is_in_tree_beads_dir(beads_dir: Path) -> bool:
    """Return whether *beads_dir* is the primary repo's ``sdd/beads`` store."""
    parts = beads_dir.parts
    return (
        len(parts) >= 2
        and parts[-2:] == ("sdd", "beads")
        and not (len(parts) >= 3 and parts[-3:] == (".sase", "sdd", "beads"))
    )


def verify_bead_store_published(
    beads_dir: Path,
    *,
    find_git_root: Callable[[Path], Path | None] = _find_git_root,
) -> BeadPublicationStatus:
    """Report whether committed bead state reached the canonical remote.

    A store with no Git root, no upstream, or an in-tree layout has no
    canonical remote of its own to publish to; those are reported as
    ``applicable=False`` and must never be treated as a publication failure.
    """
    repo_root = find_git_root(beads_dir)
    if repo_root is None or is_in_tree_beads_dir(beads_dir):
        return BeadPublicationStatus(
            beads_dir=beads_dir,
            repo_root=repo_root,
            applicable=False,
            has_upstream=False,
            unpushed_commits=0,
        )
    if not _has_tracking_upstream(repo_root):
        return BeadPublicationStatus(
            beads_dir=beads_dir,
            repo_root=repo_root,
            applicable=False,
            has_upstream=False,
            unpushed_commits=0,
        )
    return BeadPublicationStatus(
        beads_dir=beads_dir,
        repo_root=repo_root,
        applicable=True,
        has_upstream=True,
        unpushed_commits=unpushed_bead_commit_count(repo_root, beads_dir),
    )


def bead_publication_failure_lines(
    status: BeadPublicationStatus,
    *,
    description: str | None = None,
) -> list[str]:
    """Build the operator-facing diagnostic for an unpublished mutation."""
    subject = description or "bead mutation"
    lines = [
        f"ERROR: {subject} was committed locally but NOT published.",
        f"  unpublished bead commit(s): {status.unpushed_commits}",
        f"  bead store: {status.beads_dir}",
    ]
    if status.repo_root is not None:
        lines.append(f"  store repository: {status.repo_root}")
    latest = latest_bead_sync_log()
    if latest is not None:
        lines.append(f"  latest managed sync log: {latest}")
    lines.append(
        "  This mutation exists only in this checkout. It is invisible to "
        "everyone else and is destroyed if this workspace is evicted."
    )
    if status.repo_root is not None:
        lines.append(f"  Remediation: git -C {status.repo_root} push")
    return lines


def _has_tracking_upstream(repo_root: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


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
    git_dir = git_state_path_for_checkout(repo_root, "")
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


def git_state_path_for_checkout(repo_root: Path, name: str) -> Path:
    """Compatibility wrapper for resolving files in a checkout's Git dir."""
    from sase.sdd._integration_marker import git_state_path

    return git_state_path(repo_root, name)
