"""Local Git persistence for bead stores."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path


class BeadWorkLaunchCommitError(RuntimeError):
    """Raised when a bead-work launch checkpoint commit fails."""


@contextmanager
def bead_store_write_lock(beads_dir: Path) -> Iterator[bool]:
    """Hold the owning repository lock across bead materialization and git.

    The yielded boolean is true when a Git-backed store lock is active. Local
    non-Git stores still execute their mutation but have no integration writer
    to serialize with.
    """
    from sase.sdd._git_contention import store_git_write_lock
    from sase.sdd._repository_transaction import (
        SddRepositoryHealthError,
        require_sdd_repository_health,
    )

    if not beads_dir.exists():
        yield False
        return
    repo_root = find_git_root(beads_dir)
    if repo_root is None:
        yield False
        return
    with store_git_write_lock(
        repo_root,
        op="bead.store_mutation",
        mutates_worktree=True,
    ) as acquired:
        if not acquired:
            raise SddRepositoryHealthError(
                f"SDD repository {repo_root} could not acquire its store write "
                "lock; no bead files were changed"
            )
        require_sdd_repository_health(repo_root)
        yield True


def _bead_worktree_lock_factory(
    *,
    already_locked: bool,
    op: str,
) -> Callable[[Path], AbstractContextManager[bool]]:
    """Pick the store-lock acquisition for one bead worktree mutation.

    Every bead writer materializes JSONL into a shared SDD worktree and then
    commits it, so none of them may proceed unlocked. They wait on the
    worktree-mutation bound and fail closed, or hand off a lock the caller
    already owns.
    """
    from sase.sdd._git_contention import (
        handoff_store_git_write_lock,
        store_git_write_lock_factory,
    )

    if already_locked:
        return handoff_store_git_write_lock
    return store_git_write_lock_factory(op=op, mutates_worktree=True)


def git_sync(beads_dir: Path, *, already_locked: bool = False) -> None:
    """Stage bead state in git (does not commit)."""
    from sase.sdd._git_contention import run_sdd_git_write
    from sase.sdd._repository_transaction import (
        SddRepositoryHealthError,
        require_sdd_repository_health,
    )

    if not beads_dir.exists():
        return
    repo_root = find_git_root(beads_dir)
    if repo_root is None:
        return
    lock_factory = _bead_worktree_lock_factory(
        already_locked=already_locked,
        op="bead.git_sync",
    )
    with lock_factory(repo_root) as acquired:
        if not acquired:
            raise SddRepositoryHealthError(
                f"SDD repository {repo_root} could not acquire its store write "
                "lock; no bead files were staged"
            )
        require_sdd_repository_health(repo_root)
        files = _list_bead_state_changes_silent(beads_dir, repo_root)
        if not files:
            return
        run_sdd_git_write(
            ["add", "--", *files],
            cwd=repo_root,
            capture_output=True,
            check=False,
            op="bead.git_sync.add",
        )


def commit_bead_claim(
    beads_dir: Path,
    bead_id: str,
    agent_name: str,
    *,
    already_locked: bool = False,
) -> bool:
    """Commit a waiting claim locally for post-lock lifecycle publication."""
    return _commit_bead_state(
        beads_dir,
        message=f"chore(beads): claim {bead_id} for {agent_name}",
        auto_commit_type="beads",
        op_prefix="bead.claim",
        already_locked=already_locked,
    )


def commit_bead_claim_release(
    beads_dir: Path,
    bead_id: str,
    agent_name: str,
    *,
    already_locked: bool = False,
) -> bool:
    """Commit a waiting-claim release for post-lock lifecycle publication."""
    return _commit_bead_state(
        beads_dir,
        message=f"chore(beads): release claim on {bead_id} from {agent_name}",
        auto_commit_type="beads",
        op_prefix="bead.claim_release",
        already_locked=already_locked,
    )


def commit_bead_claim_reconciliation(
    beads_dir: Path,
    *,
    already_locked: bool = False,
) -> bool:
    """Commit every claim transition from one reconciliation pass."""
    return _commit_bead_state(
        beads_dir,
        message="chore(beads): reconcile bead claims",
        auto_commit_type="beads",
        op_prefix="bead.claim_reconcile",
        already_locked=already_locked,
    )


def commit_external_issue_mirror(
    beads_dir: Path,
    project: str,
    *,
    already_locked: bool = False,
) -> bool:
    """Commit every bead created, noted, closed, or reopened by one issue mirror pass."""
    return _commit_bead_state(
        beads_dir,
        message=f"chore(beads): mirror external issues for {project}",
        auto_commit_type="beads",
        op_prefix="bead.external_issue_mirror",
        already_locked=already_locked,
    )


def commit_epic_graph_checkpoint(
    beads_dir: Path,
    epic_id: str,
    *,
    already_locked: bool = False,
) -> bool:
    """Commit the complete epic graph before any worker can be spawned.

    Returns False for benign no-op cases: no git repo, no bead state, or no
    staged bead-state change after adding the store.  Callers that require
    detached workers to observe the checkpoint must separately publish the
    resulting revision.
    """
    return _commit_bead_state(
        beads_dir,
        message=f"chore(beads): checkpoint approved epic graph {epic_id}",
        auto_commit_type="beads",
        op_prefix="bead.graph_checkpoint",
        already_locked=already_locked,
    )


def commit_task_work_launch(
    beads_dir: Path,
    task_id: str,
    *,
    already_locked: bool = False,
) -> bool:
    """Commit a task bead's in-progress assignment before its worker spawns."""
    return _commit_bead_state(
        beads_dir,
        message=f"chore(beads): checkpoint task work launch {task_id}",
        auto_commit_type="beads",
        op_prefix="bead.task_work_launch",
        already_locked=already_locked,
    )


def commit_failed_work_launch_recovery(
    beads_dir: Path,
    epic_id: str,
    *,
    already_locked: bool = False,
) -> bool:
    """Commit restored state after an epic launcher spawned no agents."""
    return _commit_bead_state(
        beads_dir,
        message=f"chore(beads): recover failed work launch {epic_id}",
        auto_commit_type="beads",
        op_prefix="bead.work_launch_recovery",
        already_locked=already_locked,
    )


def commit_epic_creation_rollback(
    beads_dir: Path,
    epic_id: str,
    *,
    already_locked: bool = False,
) -> bool:
    """Commit removal of an unlaunched deterministic epic graph."""
    return _commit_bead_state(
        beads_dir,
        message=f"chore(beads): rollback deterministic epic creation {epic_id}",
        auto_commit_type="beads",
        op_prefix="bead.graph_rollback",
        already_locked=already_locked,
    )


def _commit_bead_state(
    beads_dir: Path,
    *,
    message: str,
    auto_commit_type: str,
    op_prefix: str,
    already_locked: bool,
) -> bool:
    """Commit only changed bead-state files with a stage-specific message."""
    from sase.sdd._git import run_sdd_git
    from sase.sdd._repository_transaction import (
        SddRepositoryHealthError,
        require_sdd_repository_health,
    )

    if not beads_dir.exists():
        return False
    repo_root = find_git_root(beads_dir)
    if repo_root is None:
        return False

    rel_beads = relative_pathspec(beads_dir, repo_root)
    lock_factory = _bead_worktree_lock_factory(
        already_locked=already_locked,
        op=op_prefix,
    )
    with lock_factory(repo_root) as acquired:
        if not acquired:
            raise SddRepositoryHealthError(
                f"SDD repository {repo_root} could not acquire its store write "
                "lock; no bead files were staged"
            )
        require_sdd_repository_health(repo_root)
        files = _list_bead_state_changes(beads_dir, repo_root)
        if not files:
            return False
        from sase.bead._stream_integrity import prepare_event_streams_for_commit

        prepared = prepare_event_streams_for_commit(repo_root, files)
        if prepared.restored_paths:
            files = _list_bead_state_changes(beads_dir, repo_root)
            if not files:
                return False
        _run_git_write_or_raise(
            ["add", "--", *files],
            cwd=repo_root,
            action=f"stage {rel_beads}",
            op=f"{op_prefix}.add",
        )

        diff_result = run_sdd_git(
            ["diff", "--cached", "--quiet", "--", *files],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            op=f"{op_prefix}.diff_cached",
        )
        if diff_result.returncode == 0:
            return False
        if diff_result.returncode != 1:
            raise BeadWorkLaunchCommitError(
                _format_git_failure(
                    f"inspect staged changes for {rel_beads}", diff_result
                )
            )

        from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

        message = apply_auto_commit_type_tag(message, auto_commit_type)
        _run_git_write_or_raise(
            ["commit", "-m", message, "--", *files],
            cwd=repo_root,
            action=f"commit {rel_beads}",
            op=f"{op_prefix}.commit",
        )
    return True


def bead_state_is_clean(beads_dir: Path) -> bool:
    """Return whether the bead store has no tracked or untracked git changes."""
    if not beads_dir.exists():
        return True
    repo_root = find_git_root(beads_dir)
    if repo_root is None:
        return True
    try:
        files = _list_bead_state_changes(beads_dir, repo_root)
    except BeadWorkLaunchCommitError:
        return False
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


def find_git_root(path: Path) -> Path | None:
    """Find the git root directory from a given path."""
    from sase.sdd._git import run_sdd_git

    result = run_sdd_git(
        ["rev-parse", "--show-toplevel"],
        cwd=path if path.is_dir() else path.parent,
        capture_output=True,
        text=True,
        check=False,
        op="bead.find_git_root",
    )
    if result.returncode == 0:
        return Path(result.stdout.strip())
    return None


def relative_pathspec(path: Path, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _list_bead_state_changes(beads_dir: Path, repo_root: Path) -> list[str]:
    """Return the bead-state files (relative to ``repo_root``) with
    uncommitted changes — modified, untracked, or deleted — excluding any
    files matched by ``.gitignore`` (so ``beads.db`` and its SQLite sidecars
    are never returned).
    """
    from sase.sdd._git import run_sdd_git

    rel_beads = relative_pathspec(beads_dir, repo_root)
    result = run_sdd_git(
        [
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
        op="bead.changed_files",
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


def _run_git_write_or_raise(
    args: list[str],
    *,
    cwd: Path,
    action: str,
    op: str,
) -> None:
    from sase.sdd._git_contention import run_sdd_git_write

    result = run_sdd_git_write(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        op=op,
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
