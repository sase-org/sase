"""Git sync for beads issue tracking."""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class BeadWorkLaunchCommitError(RuntimeError):
    """Raised when the post-launch bead metadata commit fails."""


@dataclass(frozen=True)
class _PushOutcome:
    """Result of attempting a post-commit ``git push``."""

    pushed: bool
    skipped_no_remote: bool
    error: str | None


@dataclass(frozen=True)
class _AsyncPushHandle:
    """Bookkeeping for a detached ``git push`` started in the background."""

    pid: int
    log_path: Path


BeadRefreshMode = Literal["background", "blocking", "off"]
_DEFAULT_REFRESH_TTL_SECONDS = 120.0
_INTEGRATION_MARKER = "sase-bead-sync.integration"


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

    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    message = apply_auto_commit_type_tag(
        f"chore: mark bead work launched for {bead_id}",
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
    """Synchronize and push the just-committed bead state.

    Returns a :class:`_PushOutcome` describing whether the push happened, was
    skipped because no remote is configured, or failed (with the error text).
    Never raises — push failures must not undo a successful local commit.
    """
    repo_root = _find_git_root(beads_dir)
    if repo_root is None:
        return _PushOutcome(pushed=False, skipped_no_remote=True, error=None)

    if not _has_push_remote(repo_root):
        return _PushOutcome(pushed=False, skipped_no_remote=True, error=None)

    from sase.bead.sync_worker import run_managed_sync_worker

    result = run_managed_sync_worker(
        repo_root,
        beads_dir.resolve(),
        log_path=_new_sync_log_path(),
    )
    if result.pushed:
        return _PushOutcome(pushed=True, skipped_no_remote=False, error=None)
    return _PushOutcome(
        pushed=False,
        skipped_no_remote=False,
        error=result.error or "managed bead sync did not push",
    )


def _has_push_remote(repo_root: Path) -> bool:
    remotes = subprocess.run(
        ["git", "remote"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return remotes.returncode == 0 and bool(remotes.stdout.strip())


def push_bead_work_launch_async(beads_dir: Path) -> _AsyncPushHandle | None:
    """Start a detached managed sync worker and return its log location.

    Returns ``None`` when there is no git repo or no configured remote (nothing
    to push). Unlike :func:`push_bead_work_launch`, this never blocks the caller
    on remote network/credential latency: the push runs in its own session with
    its output captured to a log file so ``sase bead work`` can return as soon as
    the agents are launched. Because it is detached, stdin is closed — a push
    that needs interactive credentials will fail and record the failure in the
    log rather than prompting.
    """
    repo_root = _find_git_root(beads_dir)
    if repo_root is None or not _has_push_remote(repo_root):
        return None

    log_path = _new_sync_log_path()
    with open(log_path, "w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "sase.bead.sync_worker",
                str(repo_root),
                str(beads_dir.resolve()),
                str(log_path),
            ],
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return _AsyncPushHandle(pid=process.pid, log_path=log_path)


def bead_refresh_mode() -> BeadRefreshMode:
    """Return the configured remote-freshness policy for bead commands."""
    try:
        from sase.config import load_merged_config

        raw = (
            load_merged_config()
            .get("sdd", {})
            .get("bead_refresh", {})
            .get("mode", "background")
        )
    except Exception:
        return "background"
    return raw if raw in {"background", "blocking", "off"} else "background"


def _bead_refresh_ttl_seconds() -> float:
    """Return the minimum age before another background sync is launched."""
    try:
        from sase.config import load_merged_config

        raw = (
            load_merged_config()
            .get("sdd", {})
            .get("bead_refresh", {})
            .get("ttl_seconds", _DEFAULT_REFRESH_TTL_SECONDS)
        )
        value = float(raw)
    except Exception:
        return _DEFAULT_REFRESH_TTL_SECONDS
    return max(0.0, value)


def _maybe_schedule_bead_refresh(beads_dir: Path) -> _AsyncPushHandle | None:
    """Launch a TTL-gated background integration for a warm companion store."""
    if bead_refresh_mode() != "background":
        return None
    repo_root = _find_git_root(beads_dir)
    if repo_root is None or _integration_is_fresh(repo_root):
        return None
    return push_bead_work_launch_async(beads_dir)


def schedule_current_bead_refresh() -> _AsyncPushHandle | None:
    """Best-effort post-command refresh for the currently resolved store."""
    try:
        from sase.bead.cli_common import resolve_beads_location

        location = resolve_beads_location(require_existing=True)
        if location is None or location.is_in_tree:
            return None
        return _maybe_schedule_bead_refresh(location.beads_dir)
    except Exception:
        return None


def mark_bead_integration(repo_root: Path) -> None:
    """Record a successful fetch/rebase integration for TTL gating."""
    marker = _git_state_path(repo_root, _INTEGRATION_MARKER)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()


def bead_sync_diagnostics(beads_dir: Path) -> list[str]:
    """Report convergence problems visible from the local clone."""
    repo_root = _find_git_root(beads_dir)
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
        elif ahead:
            messages.append(f"WARNING: bead store has {ahead} unpushed commit(s)")
        elif behind:
            messages.append(f"WARNING: bead store is {behind} commit(s) behind")

    if messages:
        latest = _latest_bead_sync_log()
        if latest is not None:
            messages.append(f"INFO: latest bead sync log: {latest}")
    return messages


def _latest_bead_sync_log() -> Path | None:
    """Return the newest managed-sync log, when one exists."""
    from sase.core.paths import ensure_sase_directory

    log_dir = Path(ensure_sase_directory("bead_push_logs"))
    logs = list(log_dir.glob("sync-*.log"))
    return max(logs, key=lambda path: path.stat().st_mtime, default=None)


def _new_sync_log_path() -> Path:
    from sase.core.paths import ensure_sase_directory
    from sase.core.time import generate_timestamp

    log_dir = Path(ensure_sase_directory("bead_push_logs"))
    return log_dir / f"sync-{generate_timestamp()}.log"


def _integration_is_fresh(repo_root: Path) -> bool:
    marker = _git_state_path(repo_root, _INTEGRATION_MARKER)
    try:
        age = time.time() - marker.stat().st_mtime
    except OSError:
        return False
    return age < _bead_refresh_ttl_seconds()


def _git_state_path(repo_root: Path, name: str) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    git_dir = Path(result.stdout.strip()) if result.returncode == 0 else Path(".git")
    if not git_dir.is_absolute():
        git_dir = repo_root / git_dir
    return git_dir / name if name else git_dir
