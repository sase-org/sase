"""Mixed-version-safe untracking of the ``issues.jsonl`` projection."""

from __future__ import annotations

import logging
from pathlib import Path


_logger = logging.getLogger(__name__)


def migrate_projection_off_track(beads_dir: Path, repo_root: Path) -> tuple[bool, bool]:
    """Untrack ``issues.jsonl`` and drop its stale working copy.

    Idempotent migration for projection-off (sase-1h8.11). Callers run it
    under the store lock before bead state is staged or committed, so the
    untracking lands inside the next bead commit. Event stores only;
    legacy stores without ``events/`` keep their tracked projection.

    The worktree copy is deleted but otherwise left for the caller's normal
    add/commit flow: a tracked file missing from the worktree still shows
    up in ``--deleted`` enumeration, so ``git add`` stages the deletion and
    the commit records it. (``git rm --cached`` would hide the path from
    that enumeration instead.) Nothing is staged here for the same reason:
    a staged-new ``.gitignore`` is invisible to that enumeration, so the
    ignore rule is left unstaged for the commit to pick up.

    Returns ``(changed, gitignore_updated)``: callers committing with a
    directory-scoped pathspec must also include the repo ``.gitignore``
    when the rule was amended, or the rule never lands in that commit.
    """

    if not (beads_dir / "events").is_dir():
        return False, False
    try:
        rel_beads = beads_dir.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return False, False
    if rel_beads == ".":
        rel_issues = "issues.jsonl"
        prefix = ""
    else:
        rel_issues = f"{rel_beads}/issues.jsonl"
        prefix = rel_beads
    # Old clients still regenerate the projection on every mutation. Ignore
    # it so those regenerations are never staged again.
    from sase.sdd._bead_ignore import ensure_bead_store_gitignore

    gitignore_updated = False
    try:
        if ensure_bead_store_gitignore(repo_root, prefix=prefix) is not None:
            gitignore_updated = True
    except OSError as exc:
        _logger.debug(
            "projection-off migration: could not update .gitignore in %s: %s",
            repo_root,
            exc,
        )
    # An old client's conflict resolution can re-track the file; the next
    # new-client mutation untracks it again. Only the worktree copy is
    # dropped here: copies that were never tracked (fresh `sase bead
    # export` output, old-client regenerations) are left alone.
    if not _is_tracked(repo_root, rel_issues):
        return False, gitignore_updated
    try:
        (repo_root / rel_issues).unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        _logger.debug(
            "projection-off migration: could not delete %s: %s",
            rel_issues,
            exc,
        )
        return False, gitignore_updated
    return True, gitignore_updated


def _is_tracked(repo_root: Path, rel_path: str) -> bool:
    from sase.sdd._git import run_sdd_git

    result = run_sdd_git(
        ["ls-files", "--cached", "--", rel_path],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        op="bead.projection_migration.tracked",
    )
    if result.returncode != 0:
        return False
    stdout = result.stdout
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", errors="replace")
    return any(line.strip() == rel_path for line in stdout.splitlines() if line.strip())
