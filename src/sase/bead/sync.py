"""Git sync for beads issue tracking."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class BeadWorkLaunchCommitError(RuntimeError):
    """Raised when the post-launch bead metadata commit fails."""


@dataclass(frozen=True)
class _PushOutcome:
    """Result of attempting a post-commit ``git push``."""

    pushed: bool
    skipped_no_remote: bool
    error: str | None


def git_sync(beads_dir: Path) -> None:
    """Export JSONL and stage in git (does not commit)."""
    jsonl_path = beads_dir / "issues.jsonl"
    if not jsonl_path.exists():
        return
    repo_root = _find_git_root(beads_dir)
    if repo_root is None:
        return
    # Stage the JSONL file
    subprocess.run(
        ["git", "add", str(jsonl_path)],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )


def commit_bead_work_launch(
    beads_dir: Path,
    bead_id: str,
    title: str,
    *,
    kind: str,
) -> bool:
    """Commit the JSONL bead-state mutation produced by ``sase bead work``.

    Returns False for benign no-op cases: no git repo, no JSONL file, or no
    staged JSONL change after adding the file.
    """
    del title
    jsonl_path = beads_dir / "issues.jsonl"
    if not jsonl_path.exists():
        return False
    repo_root = _find_git_root(beads_dir)
    if repo_root is None:
        return False

    rel_jsonl = _relative_pathspec(jsonl_path, repo_root)
    _run_git_or_raise(
        ["git", "add", "--", rel_jsonl],
        cwd=repo_root,
        action=f"stage {rel_jsonl}",
    )

    diff_result = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", rel_jsonl],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if diff_result.returncode == 0:
        return False
    if diff_result.returncode != 1:
        raise BeadWorkLaunchCommitError(
            _format_git_failure(f"inspect staged changes for {rel_jsonl}", diff_result)
        )

    subject_kind = "legend" if kind == "legend" else "bead"
    message = f"chore: mark {subject_kind} work launched for {bead_id}"
    _run_git_or_raise(
        ["git", "commit", "-m", message, "--", rel_jsonl],
        cwd=repo_root,
        action=f"commit {rel_jsonl}",
    )
    return True


def rebuild_from_jsonl(beads_dir: Path) -> bool:
    """Rebuild SQLite from JSONL if JSONL is newer than db.

    Returns True if rebuild was performed.
    """
    from sase.bead import db as db_mod
    from sase.bead.jsonl import import_from_jsonl

    jsonl_path = beads_dir / "issues.jsonl"
    db_path = beads_dir / "beads.db"

    if not jsonl_path.exists():
        return False

    # Rebuild if db doesn't exist or JSONL is newer
    if db_path.exists():
        jsonl_mtime = jsonl_path.stat().st_mtime
        db_mtime = db_path.stat().st_mtime
        if db_mtime >= jsonl_mtime:
            return False

    conn = db_mod.init_db(db_path)
    try:
        import_from_jsonl(jsonl_path, conn)
    finally:
        conn.close()
    return True


def _find_git_root(path: Path) -> Path | None:
    """Find the git root directory from a given path."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path if path.is_dir() else path.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return Path(result.stdout.strip())
    return None


def _relative_pathspec(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _run_git_or_raise(command: list[str], *, cwd: Path, action: str) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BeadWorkLaunchCommitError(_format_git_failure(action, result))


def _format_git_failure(
    action: str,
    result: subprocess.CompletedProcess[str],
) -> str:
    detail = (result.stderr or result.stdout or "").strip()
    if detail:
        return f"git {action} failed: {detail}"
    return f"git {action} failed with exit code {result.returncode}"


def push_bead_work_launch(beads_dir: Path) -> _PushOutcome:
    """Push the just-committed JSONL state to the configured git remote.

    Returns a :class:`_PushOutcome` describing whether the push happened, was
    skipped because no remote is configured, or failed (with the error text).
    Never raises — push failures must not undo a successful local commit.
    """
    repo_root = _find_git_root(beads_dir)
    if repo_root is None:
        return _PushOutcome(pushed=False, skipped_no_remote=True, error=None)

    remotes = subprocess.run(
        ["git", "remote"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if remotes.returncode != 0 or not remotes.stdout.strip():
        return _PushOutcome(pushed=False, skipped_no_remote=True, error=None)

    # Inherit stdin/stdout/stderr so credential prompts work for the user.
    push = subprocess.run(["git", "push"], cwd=repo_root, check=False)
    if push.returncode == 0:
        return _PushOutcome(pushed=True, skipped_no_remote=False, error=None)

    return _PushOutcome(
        pushed=False,
        skipped_no_remote=False,
        error=f"git push failed with exit code {push.returncode}",
    )
