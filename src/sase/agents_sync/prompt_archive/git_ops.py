"""Git operations for prompt archive publication."""

from __future__ import annotations

from pathlib import Path
import subprocess

from sase.agents_sync.git import GitRunner
from sase.agents_sync.git_sync_ops import AGENTS_SYNC_AUTO_COMMIT_TYPE
from sase.agents_sync.prompt_archive.archive_objects import (
    ARCHIVE_OBJECT_ROOT,
    quarantine_invalid_pending_objects,
)

# Roots rebuilt from the local artifact pool on every publication; cleaning may
# reset, restore, and delete under them.
REGENERABLE_ARCHIVE_PATHS = ("prompts", "artifacts")
# Everything a publication commits. ``files/objects`` is append-only and not
# reliably regenerable, so it is staged here but never cleaned.
PUBLISHED_ARCHIVE_PATHS = (*REGENERABLE_ARCHIVE_PATHS, ARCHIVE_OBJECT_ROOT)


def commit_prompt_archive_if_dirty(
    repo: Path,
    global_agent: str,
    git_runner: GitRunner,
) -> bool | str:
    """Commit only the incremental prompt/archive path set."""

    quarantined = quarantine_invalid_pending_objects(repo, git_runner)
    if isinstance(quarantined, str):
        return quarantined
    archive_paths = tuple(
        path
        for path in PUBLISHED_ARCHIVE_PATHS
        if (repo / path).exists() or _tracked_archive_path(repo, path, git_runner)
    )
    if not archive_paths:
        return False
    staged = git_runner(
        repo,
        ["add", "--", *archive_paths],
        op="agents_sync.prompt_archive_stage",
    )
    if staged.returncode != 0:
        return _git_error("could not stage prompt archive", staged)
    dirty = git_runner(
        repo,
        ["diff", "--cached", "--quiet", "--", *archive_paths],
        op="agents_sync.prompt_archive_diff",
    )
    if dirty.returncode == 0:
        return False
    if dirty.returncode != 1:
        return _git_error("could not inspect staged prompt archive", dirty)
    committed = _commit_as_sase(
        repo,
        f"chore(agents): archive prompt for {global_agent}",
        git_runner,
        op="agents_sync.prompt_archive_commit",
    )
    return (
        True
        if committed.returncode == 0
        else _git_error("could not commit prompt archive", committed)
    )


def publish_pending_archive_objects(
    repo: Path,
    git_runner: GitRunner,
) -> bool | str:
    """Commit hash-valid untracked ``files/objects`` and quarantine the rest.

    A pending object can predate this publication (a transaction that failed
    after writing it, or an older sase that never committed objects). Committing
    it before ``git pull --rebase`` keeps the pull from refusing to overwrite an
    identical object the remote already tracks: the identical add/add rebases
    cleanly. The caller holds the agents sync lock.
    """

    valid = quarantine_invalid_pending_objects(repo, git_runner)
    if isinstance(valid, str):
        return valid
    if not valid:
        return False
    staged = git_runner(
        repo,
        ["add", "--", *valid],
        op="agents_sync.prompt_archive_objects_stage",
    )
    if staged.returncode != 0:
        return _git_error("could not stage pending prompt archive objects", staged)
    committed = _commit_as_sase(
        repo,
        "chore(agents): publish pending prompt-archive objects",
        git_runner,
        op="agents_sync.prompt_archive_objects_commit",
        paths=valid,
    )
    return (
        True
        if committed.returncode == 0
        else _git_error("could not commit pending prompt archive objects", committed)
    )


def clean_prompt_archive_worktree(repo: Path, git_runner: GitRunner) -> str | None:
    """Restore the regenerable prompt archive paths to ``HEAD``.

    ``files/objects`` is deliberately absent: it is append-only, so nothing here
    resets, restores, or cleans under it.
    """

    reset = git_runner(
        repo,
        ["reset", "--quiet", "HEAD", "--", *REGENERABLE_ARCHIVE_PATHS],
        op="agents_sync.prompt_archive_reset",
    )
    if reset.returncode != 0:
        return _git_error("could not reset prompt archive index", reset)
    tracked = git_runner(
        repo,
        ["ls-files", "--", *REGENERABLE_ARCHIVE_PATHS],
        op="agents_sync.prompt_archive_tracked",
    )
    if tracked.returncode != 0:
        return _git_error("could not inspect tracked prompt archive", tracked)
    restore_roots = tuple(
        root
        for root in REGENERABLE_ARCHIVE_PATHS
        if any(
            path == root or path.startswith(f"{root}/")
            for path in tracked.stdout.splitlines()
        )
    )
    if restore_roots:
        restored = git_runner(
            repo,
            ["checkout", "--", *restore_roots],
            op="agents_sync.prompt_archive_restore",
        )
        if restored.returncode != 0:
            return _git_error("could not restore prompt archive", restored)
    cleaned = git_runner(
        repo,
        ["clean", "-fd", "--", *REGENERABLE_ARCHIVE_PATHS],
        op="agents_sync.prompt_archive_clean",
    )
    return (
        None
        if cleaned.returncode == 0
        else _git_error("could not clean prompt archive", cleaned)
    )


def _commit_as_sase(
    repo: Path,
    message: str,
    git_runner: GitRunner,
    *,
    op: str,
    paths: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    """Commit as SASE with the agents-sync tag, limited to ``paths`` if given."""

    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    return git_runner(
        repo,
        [
            "-c",
            "user.name=SASE",
            "-c",
            "user.email=sase@localhost",
            "commit",
            "-m",
            apply_auto_commit_type_tag(message, AGENTS_SYNC_AUTO_COMMIT_TYPE),
            *(("--", *paths) if paths else ()),
        ],
        op=op,
    )


def _tracked_archive_path(repo: Path, path: str, git_runner: GitRunner) -> bool:
    result = git_runner(
        repo,
        ["ls-files", "--", path],
        op="agents_sync.prompt_archive_path_tracked",
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _git_error(
    prefix: str,
    result: subprocess.CompletedProcess[str],
) -> str:
    detail = (result.stderr or result.stdout or "unknown git error").strip()
    return f"{prefix}: {detail}"


__all__ = [
    "PUBLISHED_ARCHIVE_PATHS",
    "REGENERABLE_ARCHIVE_PATHS",
    "clean_prompt_archive_worktree",
    "commit_prompt_archive_if_dirty",
    "publish_pending_archive_objects",
]
