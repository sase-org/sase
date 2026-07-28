"""Remote synchronization and public sync API for bead stores."""

from __future__ import annotations

from collections import Counter
import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.bead._sync_git import (
    BeadWorkLaunchCommitError as BeadWorkLaunchCommitError,
)
from sase.bead._sync_git import (
    bead_state_is_clean as bead_state_is_clean,
    bead_store_write_lock as bead_store_write_lock,
    commit_bead_claim as commit_bead_claim,
    commit_bead_claim_reconciliation as commit_bead_claim_reconciliation,
    commit_bead_claim_release as commit_bead_claim_release,
    commit_bead_work_launch as commit_bead_work_launch,
    commit_epic_creation_rollback as commit_epic_creation_rollback,
    commit_epic_graph_checkpoint as commit_epic_graph_checkpoint,
    commit_failed_work_launch_recovery as commit_failed_work_launch_recovery,
    find_git_root as _find_git_root,
    git_sync as git_sync,
    rebuild_from_jsonl as rebuild_from_jsonl,
    relative_pathspec as _relative_pathspec,
)


BeadRefreshMode = Literal["background", "blocking", "off"]

_DEEP_DIVERGENCE_SIDE_THRESHOLD = 3
_SYNC_LOG_SCAN_LIMIT = 64
_SYNC_LOG_HEAD_BYTES = 8 * 1024
_SYNC_LOG_TAIL_BYTES = 64 * 1024
_SYNC_LOG_RECURRING_FAILURE_THRESHOLD = 2


class _BeadStoreRefreshError(RuntimeError):
    """Raised when a blocking refresh cannot integrate the bead store."""


@dataclass(frozen=True)
class _SyncLogOutcome:
    """Parsed terminal outcome from one managed-sync log."""

    path: Path
    repo_root: str
    terminal_event: Literal["completed", "failed", "skipped"] | None
    error_class: str | None
    error: str | None


@dataclass(frozen=True)
class _PushOutcome:
    """Result of attempting a post-commit ``git push``."""

    pushed: bool
    skipped_no_remote: bool
    error: str | None
    log_path: Path | None = None


@dataclass(frozen=True)
class _AsyncPushHandle:
    """Bookkeeping for a detached ``git push`` started in the background."""

    pid: int
    log_path: Path


def push_bead_work_launch(beads_dir: Path) -> _PushOutcome:
    """Synchronize and push the just-committed bead state.

    Returns a :class:`_PushOutcome` describing whether the push happened, was
    skipped because no remote is configured, or failed (with the error text).
    Never raises — push failures must not undo a successful local commit.
    """
    try:
        repo_root = _find_git_root(beads_dir)
        if repo_root is None:
            return _PushOutcome(pushed=False, skipped_no_remote=True, error=None)

        if not _has_push_remote(repo_root):
            return _PushOutcome(pushed=False, skipped_no_remote=True, error=None)

        from sase.bead.sync_worker import run_managed_sync_worker

        log_path = _new_sync_log_path()
        semantic_beads_dir = _semantic_beads_dir_for_sync(repo_root, beads_dir)
        result = run_managed_sync_worker(
            repo_root,
            semantic_beads_dir,
            log_path=log_path,
        )
        if result.pushed:
            return _PushOutcome(
                pushed=True,
                skipped_no_remote=False,
                error=None,
                log_path=log_path,
            )
        return _PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error=result.error or "managed bead sync did not push",
            log_path=log_path,
        )
    except Exception as exc:  # noqa: BLE001 - this API must never raise.
        return _PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error=str(exc) or type(exc).__name__,
        )


def publish_bead_claim(
    beads_dir: Path,
    bead_id: str,
    agent_name: str,
) -> _PushOutcome:
    """Synchronously publish one runner-owned bead claim transition.

    Missing repositories and remotes are benign local-only outcomes. Any real
    managed-sync failure is reported with claim context and its log location,
    while the caller's already-created local commit remains intact.
    """
    if _is_in_tree_beads_dir(beads_dir):
        return _PushOutcome(pushed=False, skipped_no_remote=True, error=None)

    try:
        outcome = push_bead_work_launch(beads_dir)
    except Exception as exc:  # noqa: BLE001 - publication must preserve claims.
        outcome = _PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error=str(exc),
        )

    if outcome.error:
        detail = outcome.error
        if outcome.log_path is not None:
            detail = f"{detail} (managed sync log: {outcome.log_path})"
        print(
            f"Warning: Failed to publish bead claim transition for bead "
            f"'{bead_id}' and agent '{agent_name}': {detail}",
            file=sys.stderr,
        )
    return outcome


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

    semantic_beads_dir = _semantic_beads_dir_for_sync(repo_root, beads_dir)
    log_path = _new_sync_log_path()
    # Append rather than truncate: the worker writes its own JSON records to
    # this same file, so a child traceback must land after them, not over them.
    with open(log_path, "a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "sase.bead.sync_worker",
                str(repo_root),
                str(semantic_beads_dir),
                str(log_path),
            ],
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return _AsyncPushHandle(pid=process.pid, log_path=log_path)


def _semantic_beads_dir_for_sync(repo_root: Path, requested_path: Path) -> Path:
    """Preserve the bead-store prefix when a generic caller passes a repo root."""

    requested = requested_path.expanduser().resolve()
    root = repo_root.expanduser().resolve()
    if requested != root:
        return requested

    from sase.bead.conflict_resolver import resolve_beads_dir

    return resolve_beads_dir(root) or requested


def _maybe_schedule_bead_refresh(beads_dir: Path) -> _AsyncPushHandle | None:
    """Launch a TTL-gated background integration for a warm sidecar store."""
    if bead_refresh_mode() != "background":
        return None
    repo_root = _find_git_root(beads_dir)
    if repo_root is None or _integration_is_fresh(repo_root):
        return None
    return push_bead_work_launch_async(beads_dir)


def bead_refresh_mode() -> BeadRefreshMode:
    """Return the configured remote-freshness policy for bead commands."""
    from sase.sdd._integration_marker import bead_refresh_mode as sdd_refresh_mode

    return sdd_refresh_mode()


def _integration_is_fresh(repo_root: Path) -> bool:
    """Compatibility wrapper for the SDD-owned integration marker."""
    from sase.sdd._integration_marker import integration_is_fresh

    return integration_is_fresh(repo_root)


def mark_bead_integration(repo_root: Path) -> None:
    """Compatibility wrapper for the SDD-owned integration marker."""
    from sase.sdd._integration_marker import mark_bead_integration as mark_integration

    mark_integration(repo_root)


def bead_store_git_root(path: Path) -> Path | None:
    """Return the Git worktree root owning a bead-store path, when present."""
    return _find_git_root(path)


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


def refresh_current_bead_store() -> None:
    """Synchronously integrate the current remote-backed bead store.

    In-tree and non-remote stores need no integration. Unlike the managed sync
    worker, this read-recovery path deliberately stops after fetch/rebase and
    never pushes local state.
    """
    from sase.bead.cli_common import resolve_beads_location

    location = resolve_beads_location(require_existing=True)
    if (
        location is None
        or location.is_in_tree
        or location.store is None
        or not location.store.remote_url
    ):
        return

    refresh_bead_store(location.beads_dir)


def refresh_bead_store(beads_dir: Path, *, lock_timeout: float | None = None) -> None:
    """Synchronously integrate one remote-backed project bead store.

    A recovery refresh is serialized with other store writers. The integration
    marker lets waiters skip work when another process completed the same
    recovery after they started waiting for the lock.

    ``lock_timeout`` bounds only the wait for the store write lock. A caller
    that runs under its own deadline (the ``bead_store_refresh`` chop) passes a
    bound below that deadline so a contended clone raises promptly instead of
    waiting out the default worktree-mutation timeout; the default ``None``
    keeps the shared bound for callers without one.
    """
    beads_dir = beads_dir.expanduser().resolve()
    if _is_in_tree_beads_dir(beads_dir):
        return

    repo_root = _find_git_root(beads_dir)
    if repo_root is None or not _has_push_remote(repo_root):
        return

    from sase.sdd._git_contention import (
        handoff_store_git_write_lock,
        store_git_write_lock,
    )
    from sase.sdd._integration_marker import integration_marker_generation
    from sase.sdd._repository_recovery_markers import (
        clear_failed_integration_marker,
    )
    from sase.sdd._repository_transaction import integrate_sdd_repository

    observed_generation = integration_marker_generation(repo_root)
    with store_git_write_lock(
        repo_root,
        timeout=lock_timeout,
        op="bead.refresh",
        mutates_worktree=True,
    ) as acquired:
        current_generation = integration_marker_generation(repo_root)
        if current_generation is not None and current_generation != observed_generation:
            return
        if not acquired:
            raise _BeadStoreRefreshError(
                f"could not acquire the bead-store refresh lock for {repo_root}"
            )
        outcome = integrate_sdd_repository(
            repo_root,
            beads_dir=beads_dir,
            op_prefix="bead.refresh",
            lock_factory=handoff_store_git_write_lock,
        )
        if outcome.succeeded:
            # Any successful integration ends the clone's failed-integration
            # cooldown, not only the pull path that recorded it.
            clear_failed_integration_marker(
                repo_root,
                lock_factory=handoff_store_git_write_lock,
            )
    if outcome.succeeded:
        return

    detail = outcome.error or f"SDD integration ended with {outcome.status.value}"
    raise _BeadStoreRefreshError(detail)


def _is_in_tree_beads_dir(beads_dir: Path) -> bool:
    """Return whether *beads_dir* is the primary repo's ``sdd/beads`` store."""
    parts = beads_dir.parts
    return (
        len(parts) >= 2
        and parts[-2:] == ("sdd", "beads")
        and not (len(parts) >= 3 and parts[-3:] == (".sase", "sdd", "beads"))
    )


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
            bead_commits = unpushed_bead_commit_count(
                repo_root,
                beads_dir,
            )
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
        [
            "git",
            "for-each-ref",
            "--format=%(refname)",
            RECOVERY_REF_PREFIX,
        ],
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

    messages.extend(_managed_sync_log_diagnostics(repo_root))

    if messages:
        latest = _latest_bead_sync_log()
        if latest is not None:
            messages.append(f"INFO: latest bead sync log: {latest}")
    return messages


def _managed_sync_log_diagnostics(repo_root: Path) -> list[str]:
    """Return bounded warnings for recurring same-clone managed-sync failures."""
    try:
        repo_key = _normalized_path_string(repo_root)
        outcomes: list[_SyncLogOutcome] = []
        for path in _recent_bead_sync_log_paths():
            outcome = _parse_sync_log_outcome(path)
            if outcome is not None and outcome.repo_root == repo_key:
                outcomes.append(outcome)
    except Exception:
        return []

    failures: list[_SyncLogOutcome] = []
    for outcome in outcomes:
        if outcome.terminal_event == "failed":
            failures.append(outcome)
            continue
        if outcome.terminal_event == "completed":
            break

    failure_count = len(failures)
    if failure_count < _SYNC_LOG_RECURRING_FAILURE_THRESHOLD:
        return []

    class_counts = Counter(
        outcome.error_class or "unknown failure" for outcome in failures
    )
    dominant_class, dominant_count = class_counts.most_common(1)[0]
    return [
        "WARNING: bead managed sync has "
        f"{failure_count} consecutive failed integration(s) for this clone; "
        f"dominant error class: {dominant_class} "
        f"({dominant_count}/{failure_count}); latest failure log: {failures[0].path}"
    ]


def _recent_bead_sync_log_paths(limit: int = _SYNC_LOG_SCAN_LIMIT) -> list[Path]:
    try:
        logs = list(_bead_sync_log_dir().glob("sync-*.log"))
    except Exception:
        return []

    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return -1.0

    return sorted(logs, key=mtime, reverse=True)[:limit]


def _parse_sync_log_outcome(path: Path) -> _SyncLogOutcome | None:
    records = _read_sync_log_records(path)
    if not records:
        return None

    repo_root: str | None = None
    terminal_event: Literal["completed", "failed", "skipped"] | None = None
    error: str | None = None
    for record in records:
        event = record.get("event")
        if event == "started":
            repo_root = (
                _normalize_logged_repo_root(record.get("repo_root")) or repo_root
            )
        if event in {"completed", "failed", "skipped"}:
            terminal_event = event
            raw_error = record.get("error")
            error = raw_error if isinstance(raw_error, str) and raw_error else None

    if repo_root is None:
        return None
    return _SyncLogOutcome(
        path=path,
        repo_root=repo_root,
        terminal_event=terminal_event,
        error_class=_classify_sync_error(error) if error else None,
        error=error,
    )


def _read_sync_log_records(path: Path) -> list[dict[str, Any]]:
    try:
        with open(path, "rb") as log_file:
            size = log_file.seek(0, os.SEEK_END)
            log_file.seek(0)
            if size <= _SYNC_LOG_HEAD_BYTES + _SYNC_LOG_TAIL_BYTES:
                chunks = [log_file.read(_SYNC_LOG_HEAD_BYTES + _SYNC_LOG_TAIL_BYTES)]
            else:
                chunks = [log_file.read(_SYNC_LOG_HEAD_BYTES)]
                log_file.seek(size - _SYNC_LOG_TAIL_BYTES)
                log_file.readline()
                chunks.append(log_file.read(_SYNC_LOG_TAIL_BYTES))
    except OSError:
        return []

    text = b"\n".join(chunks).decode("utf-8", errors="replace")
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _classify_sync_error(error: str) -> str:
    text = error.lower()
    if (
        "semantic bead conflict resolution failed" in text
        or "non-append-only bead event stream" in text
        or "rewrote base event" in text
        or "git rebase failed" in text
        or "rebase --continue failed" in text
        or "could not apply" in text
    ):
        return "unresolved rebase"
    if (
        "non-fast-forward" in text
        or "failed to push some refs" in text
        or "fetch first" in text
        or "git push rejected" in text
        or "git push failed" in text
    ):
        return "push rejection"
    if "staged changes" in text:
        return "staged-change refusal"
    if "tracked worktree changes" in text or "dirty worktree" in text:
        return "dirty-worktree refusal"
    if "uncommitted changes" in text:
        return "uncommitted-change refusal"
    if "store_write_lock_unavailable" in text or "could not acquire" in text:
        return "lock contention"
    if (
        "permission denied" in text
        or "could not read username" in text
        or "authentication" in text
        or "publickey" in text
        or "terminal prompts disabled" in text
        or "repository not found" in text
    ):
        return "credential failure"
    return "other failure"


def _normalize_logged_repo_root(raw: object) -> str | None:
    if not isinstance(raw, str) or not raw:
        return None
    return _normalized_path_string(Path(raw))


def _normalized_path_string(path: Path) -> str:
    try:
        return str(path.expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        return str(path.expanduser().absolute())


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


def _latest_bead_sync_log() -> Path | None:
    """Return the newest managed-sync log, when one exists."""
    try:
        logs = list(_bead_sync_log_dir().glob("sync-*.log"))
    except Exception:
        return None

    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return -1.0

    return max(logs, key=mtime, default=None)


def _bead_sync_log_dir() -> Path:
    """Return the managed-sync log directory."""
    from sase.core.paths import ensure_sase_directory

    return Path(ensure_sase_directory("bead_push_logs"))


def _new_sync_log_path() -> Path:
    """Return a fresh managed-sync log path that no concurrent push can reuse.

    The timestamp is second-granular, so the pid/uuid suffix is what keeps two
    pushes started in the same second from writing over each other's records.
    """
    from sase.core.paths import ensure_sase_directory
    from sase.core.time import generate_timestamp

    log_dir = Path(ensure_sase_directory("bead_push_logs"))
    suffix = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    return log_dir / f"sync-{generate_timestamp()}-{suffix}.log"


def _git_state_path(repo_root: Path, name: str) -> Path:
    """Compatibility wrapper for resolving files in a checkout's Git dir."""
    from sase.sdd._integration_marker import git_state_path

    return git_state_path(repo_root, name)
