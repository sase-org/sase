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
    """Stage bead state in git (does not commit)."""
    if not beads_dir.exists():
        return
    repo_root = _find_git_root(beads_dir)
    if repo_root is None:
        return
    files = _list_bead_state_changes_silent(beads_dir, repo_root)
    if not files:
        return
    subprocess.run(
        ["git", "add", "--", *files],
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
    """Commit the bead-state mutation produced by ``sase bead work``.

    Returns False for benign no-op cases: no git repo, no bead state, or no
    staged bead-state change after adding the store.
    """
    del title
    if not beads_dir.exists():
        return False
    repo_root = _find_git_root(beads_dir)
    if repo_root is None:
        return False

    rel_beads = _relative_pathspec(beads_dir, repo_root)
    files = _list_bead_state_changes(beads_dir, repo_root)
    if not files:
        return False

    _run_git_or_raise(
        ["git", "add", "--", *files],
        cwd=repo_root,
        action=f"stage {rel_beads}",
    )

    diff_result = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *files],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if diff_result.returncode == 0:
        return False
    if diff_result.returncode != 1:
        raise BeadWorkLaunchCommitError(
            _format_git_failure(f"inspect staged changes for {rel_beads}", diff_result)
        )

    subject_kind = "legend" if kind == "legend" else "bead"
    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    message = apply_auto_commit_type_tag(
        f"chore: mark {subject_kind} work launched for {bead_id}",
        "bead_work",
    )
    _run_git_or_raise(
        ["git", "commit", "-m", message, "--", *files],
        cwd=repo_root,
        action=f"commit {rel_beads}",
    )
    return True


def bead_state_is_clean(beads_dir: Path) -> bool:
    """Return whether the bead store has no tracked or untracked git changes."""
    if not beads_dir.exists():
        return True
    repo_root = _find_git_root(beads_dir)
    if repo_root is None:
        return True
    try:
        files = _list_bead_state_changes(beads_dir, repo_root)
    except BeadWorkLaunchCommitError:
        return True
    return not files


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


def _list_bead_state_changes(beads_dir: Path, repo_root: Path) -> list[str]:
    """Return the bead-state files (relative to ``repo_root``) with
    uncommitted changes — modified, untracked, or deleted — excluding any
    files matched by ``.gitignore`` (so ``beads.db`` and its SQLite sidecars
    are never returned).
    """
    rel_beads = _relative_pathspec(beads_dir, repo_root)
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--modified",
            "--others",
            "--deleted",
            "--exclude-standard",
            "-z",
            "--",
            f"{rel_beads}/",
        ],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()
        action = f"enumerate bead-state changes under {rel_beads}"
        if detail:
            message = f"git {action} failed: {detail}"
        else:
            message = f"git {action} failed with exit code {result.returncode}"
        raise BeadWorkLaunchCommitError(message)
    db_prefix = f"{rel_beads}/beads.db"
    seen: dict[str, None] = {}
    for entry in result.stdout.split(b"\x00"):
        if not entry:
            continue
        path = entry.decode()
        # Belt-and-suspenders: drop SQLite store paths even if .gitignore is
        # not configured (e.g. in some test setups). Production always
        # gitignores these, so this matches old pathspec-exclude semantics.
        tail = path[len(db_prefix) :] if path.startswith(db_prefix) else None
        if tail is not None and (tail == "" or tail.startswith("-")):
            continue
        seen.setdefault(path, None)
    return list(seen)


def _list_bead_state_changes_silent(beads_dir: Path, repo_root: Path) -> list[str]:
    """Best-effort variant of :func:`_list_bead_state_changes` that swallows
    subprocess failure, preserving ``git_sync``'s fire-and-forget contract.
    """
    try:
        return _list_bead_state_changes(beads_dir, repo_root)
    except BeadWorkLaunchCommitError:
        return []


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
