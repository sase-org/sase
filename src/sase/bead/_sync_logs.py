"""Managed-sync log creation, parsing, and failure diagnostics."""

from __future__ import annotations

from collections import Counter
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


_SYNC_LOG_SCAN_LIMIT = 64
_SYNC_LOG_HEAD_BYTES = 8 * 1024
_SYNC_LOG_TAIL_BYTES = 64 * 1024
_SYNC_LOG_RECURRING_FAILURE_THRESHOLD = 2


@dataclass(frozen=True)
class _SyncLogOutcome:
    """Parsed terminal outcome from one managed-sync log."""

    path: Path
    repo_root: str
    terminal_event: Literal["completed", "failed", "skipped"] | None
    error_class: str | None
    error: str | None


def managed_sync_log_diagnostics(repo_root: Path) -> list[str]:
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
    if (
        "held the store lock for the full" in text
        or "store_write_lock_unavailable" in text
        or "could not acquire" in text
    ):
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


def latest_bead_sync_log() -> Path | None:
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


def new_sync_log_path() -> Path:
    """Return a fresh managed-sync log path that no concurrent push can reuse."""
    from sase.core.paths import ensure_sase_directory
    from sase.core.time import generate_timestamp

    log_dir = Path(ensure_sase_directory("bead_push_logs"))
    suffix = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    return log_dir / f"sync-{generate_timestamp()}-{suffix}.log"
