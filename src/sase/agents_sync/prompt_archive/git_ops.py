"""Git operations for prompt archive publication."""

from __future__ import annotations

from pathlib import Path
import subprocess

from sase.agents_sync.git import GitRunner

_ARCHIVE_PATHS = ("prompts", "artifacts")


def commit_prompt_archive_if_dirty(
    repo: Path,
    global_agent: str,
    git_runner: GitRunner,
) -> bool | str:
    """Commit only the incremental prompt/archive path set."""

    archive_paths = tuple(
        path
        for path in _ARCHIVE_PATHS
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
    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    committed = git_runner(
        repo,
        [
            "-c",
            "user.name=SASE",
            "-c",
            "user.email=sase@localhost",
            "commit",
            "-m",
            apply_auto_commit_type_tag(
                f"chore(agents): archive prompt for {global_agent}", "agents_sync"
            ),
        ],
        op="agents_sync.prompt_archive_commit",
    )
    return (
        True
        if committed.returncode == 0
        else _git_error("could not commit prompt archive", committed)
    )


def clean_prompt_archive_worktree(repo: Path, git_runner: GitRunner) -> str | None:
    """Restore the regenerable prompt archive paths to ``HEAD``."""

    reset = git_runner(
        repo,
        ["reset", "--quiet", "HEAD", "--", *_ARCHIVE_PATHS],
        op="agents_sync.prompt_archive_reset",
    )
    if reset.returncode != 0:
        return _git_error("could not reset prompt archive index", reset)
    tracked = git_runner(
        repo,
        ["ls-files", "--", *_ARCHIVE_PATHS],
        op="agents_sync.prompt_archive_tracked",
    )
    if tracked.returncode != 0:
        return _git_error("could not inspect tracked prompt archive", tracked)
    restore_roots = tuple(
        root
        for root in _ARCHIVE_PATHS
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
        ["clean", "-fd", "--", *_ARCHIVE_PATHS],
        op="agents_sync.prompt_archive_clean",
    )
    return (
        None
        if cleaned.returncode == 0
        else _git_error("could not clean prompt archive", cleaned)
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
    "clean_prompt_archive_worktree",
    "commit_prompt_archive_if_dirty",
]
