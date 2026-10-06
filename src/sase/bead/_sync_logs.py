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

_PUSH_LOG_RETENTION_MARKER_FILENAME = ".bead_push_log_retention"
_DEFAULT_PUSH_LOG_MAX_AGE_DAYS = 30.0
_DEFAULT_PUSH_LOG_KEEP_COUNT = 200
_DEFAULT_PUSH_LOG_MIN_INTERVAL_SECONDS = 3600.0


def bead_push_log_retention_config() -> tuple[float, int, float]:
    """Return ``(max_age_days, keep_count, min_interval_seconds)``.

    A non-positive value disables that predicate. Falls back to defaults when
    configuration is missing or malformed.
    """

    try:
        from sase.config import load_merged_config

        raw = load_merged_config().get("sdd", {}).get("bead_push_log_retention", {})
    except Exception:
        return (
            _DEFAULT_PUSH_LOG_MAX_AGE_DAYS,
            _DEFAULT_PUSH_LOG_KEEP_COUNT,
            _DEFAULT_PUSH_LOG_MIN_INTERVAL_SECONDS,
        )
    if not isinstance(raw, dict):
        return (
            _DEFAULT_PUSH_LOG_MAX_AGE_DAYS,
            _DEFAULT_PUSH_LOG_KEEP_COUNT,
            _DEFAULT_PUSH_LOG_MIN_INTERVAL_SECONDS,
        )
    try:
        max_age_days = float(raw.get("max_age_days", _DEFAULT_PUSH_LOG_MAX_AGE_DAYS))
    except (TypeError, ValueError):
        max_age_days = _DEFAULT_PUSH_LOG_MAX_AGE_DAYS
    try:
        keep_count = int(raw.get("keep_count", _DEFAULT_PUSH_LOG_KEEP_COUNT))
    except (TypeError, ValueError):
        keep_count = _DEFAULT_PUSH_LOG_KEEP_COUNT
    try:
        min_interval_seconds = float(
            raw.get("min_interval_seconds", _DEFAULT_PUSH_LOG_MIN_INTERVAL_SECONDS)
        )
    except (TypeError, ValueError):
        min_interval_seconds = _DEFAULT_PUSH_LOG_MIN_INTERVAL_SECONDS
    return (max_age_days, keep_count, max(0.0, min_interval_seconds))


def prune_old_bead_sync_logs(
    *,
    now: float | None = None,
    max_age_days: float | None = None,
    keep_count: int | None = None,
    min_interval_seconds: float | None = None,
    log_dir: Path | None = None,
) -> int:
    """Delete ``sync-*.log`` files beyond the age-plus-count budget.

    Keeps the newest *keep_count* logs and any log younger than
    *max_age_days* (a non-positive value disables that predicate). Runs at
    most once per *min_interval_seconds* so the scheduler chop's maintenance
    pass stays cheap. Returns the number of files deleted. Best-effort: every
    filesystem failure is swallowed.
    """

    import time

    config_max_age, config_keep, config_interval = bead_push_log_retention_config()
    if max_age_days is None:
        max_age_days = config_max_age
    if keep_count is None:
        keep_count = config_keep
    if min_interval_seconds is None:
        min_interval_seconds = config_interval
    moment = now if now is not None else time.time()

    try:
        directory = log_dir if log_dir is not None else bead_sync_log_dir()
    except Exception:
        return 0

    marker = directory / _PUSH_LOG_RETENTION_MARKER_FILENAME
    try:
        last_run = marker.stat().st_mtime
    except OSError:
        last_run = 0.0
    if moment - last_run < max(0.0, min_interval_seconds):
        return 0
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch(exist_ok=True)
        os.utime(marker, (moment, moment))
    except OSError:
        pass

    try:
        logs = list(directory.glob("sync-*.log"))
    except Exception:
        return 0

    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return float("inf")

    ordered = sorted(logs, key=lambda path: (mtime(path), path.name), reverse=True)
    cutoff = moment - max(0.0, max_age_days) * 86400.0 if max_age_days > 0 else None

    deleted = 0
    for index, path in enumerate(ordered):
        if keep_count > 0 and index < keep_count:
            continue
        if cutoff is not None and mtime(path) >= cutoff:
            continue
        try:
            path.unlink()
        except OSError:
            continue
        deleted += 1
    return deleted


@dataclass(frozen=True)
class SyncLogOutcome:
    """Parsed terminal outcome from one managed-sync log."""

    path: Path
    repo_root: str
    terminal_event: Literal["completed", "failed", "skipped"] | None
    error_class: str | None
    error: str | None


def managed_sync_log_diagnostics(repo_root: Path) -> list[str]:
    """Return bounded warnings for recurring same-clone managed-sync failures."""
    try:
        repo_key = normalized_path_string(repo_root)
        outcomes: list[SyncLogOutcome] = []
        for path in recent_bead_sync_log_paths():
            outcome = parse_sync_log_outcome(path)
            if outcome is not None and outcome.repo_root == repo_key:
                outcomes.append(outcome)
    except Exception:
        return []

    failures: list[SyncLogOutcome] = []
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


def recent_bead_sync_log_paths(limit: int = _SYNC_LOG_SCAN_LIMIT) -> list[Path]:
    try:
        logs = list(bead_sync_log_dir().glob("sync-*.log"))
    except Exception:
        return []

    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return -1.0

    return sorted(logs, key=mtime, reverse=True)[:limit]


def parse_sync_log_outcome(path: Path) -> SyncLogOutcome | None:
    records = read_sync_log_records(path)
    if not records:
        return None

    repo_root: str | None = None
    terminal_event: Literal["completed", "failed", "skipped"] | None = None
    error: str | None = None
    for record in records:
        event = record.get("event")
        if event == "started":
            repo_root = normalize_logged_repo_root(record.get("repo_root")) or repo_root
        if event in {"completed", "failed", "skipped"}:
            terminal_event = event
            raw_error = record.get("error")
            error = raw_error if isinstance(raw_error, str) and raw_error else None

    if repo_root is None:
        return None
    return SyncLogOutcome(
        path=path,
        repo_root=repo_root,
        terminal_event=terminal_event,
        error_class=classify_sync_error(error) if error else None,
        error=error,
    )


def read_sync_log_records(path: Path) -> list[dict[str, Any]]:
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


def classify_sync_error(error: str) -> str:
    text = error.lower()
    if (
        "cannot publish non-append-only bead event stream" in text
        or "is shorter than its own history" in text
        or "worktree rewrote ancestor event" in text
        or "HEAD missing ancestor events" in text
    ):
        return "event-stream integrity"
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


def normalize_logged_repo_root(raw: object) -> str | None:
    if not isinstance(raw, str) or not raw:
        return None
    return normalized_path_string(Path(raw))


def normalized_path_string(path: Path) -> str:
    try:
        return str(path.expanduser().resolve(strict=False))
    except (OSError, RuntimeError):
        return str(path.expanduser().absolute())


def latest_bead_sync_log() -> Path | None:
    """Return the newest managed-sync log, when one exists."""
    try:
        logs = list(bead_sync_log_dir().glob("sync-*.log"))
    except Exception:
        return None

    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return -1.0

    return max(logs, key=mtime, default=None)


def bead_sync_log_dir() -> Path:
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
