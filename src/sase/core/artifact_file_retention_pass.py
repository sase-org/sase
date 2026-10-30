"""Indexed artifact-file retention pass shared by housekeeping and the runner.

The hourly ``artifact_retention`` job is the primary owner. Agent finalization
only runs this pass when the last completed stamp is missing or older than 24
hours, so a machine without a scheduler still enforces retention at least
daily. Overlapping passes are excluded with a non-blocking exclusive lock.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import errno
import fcntl
import json
from pathlib import Path
from typing import Any, Literal

from sase.core.atomic_json import write_json_marker_atomic
from sase.core.paths import sase_home

_INLINE_FALLBACK_MAX_AGE = timedelta(hours=24)
"""Runner inline fallback runs only when the stamp is this old or missing."""

STAMP_FILENAME = "artifact_retention.json"
LOCK_FILENAME = "artifact_retention.lock"

RetentionOutcome = Literal[
    "enforced",
    "disabled",
    "protection_unavailable",
    "failed",
    "lock_busy",
    "stamp_fresh",
]


@dataclass(frozen=True)
class _ArtifactRetentionPassResult:
    """Outcome of one retention attempt, including skips that do not stamp."""

    outcome: RetentionOutcome
    stamped: bool
    completed_at: str | None = None
    rows_trashed: int = 0
    bytes_reclaimed: int = 0
    purged_entries: int = 0
    missing_rows: int = 0
    sources_unavailable: tuple[str, ...] = ()
    error: str | None = None


def _artifact_retention_stamp_path() -> Path:
    """Return the stamp written after every completed retention pass."""

    return sase_home() / STAMP_FILENAME


def _artifact_retention_lock_path() -> Path:
    """Return the flock file that excludes overlapping retention passes."""

    return sase_home() / LOCK_FILENAME


def _read_artifact_retention_stamp() -> dict[str, Any] | None:
    """Return the last completed-pass stamp, or ``None`` when missing."""

    path = _artifact_retention_stamp_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _artifact_retention_stamp_is_fresh(*, now: datetime | None = None) -> bool:
    """Return whether the last completed pass finished within 24 hours."""

    stamp = _read_artifact_retention_stamp()
    if stamp is None:
        return False
    completed = _parse_completed_at(stamp.get("completed_at"))
    if completed is None:
        return False
    current = now if now is not None else datetime.now(UTC)
    return current - completed < _INLINE_FALLBACK_MAX_AGE


def maybe_enforce_artifact_retention() -> _ArtifactRetentionPassResult:
    """Run retention only when the stamp is missing or older than 24 hours.

    Skip immediately when another pass holds the exclusive lock. A fresh stamp
    skips without taking the lock.
    """

    if _artifact_retention_stamp_is_fresh():
        return _ArtifactRetentionPassResult(outcome="stamp_fresh", stamped=False)
    return enforce_artifact_retention()


def enforce_artifact_retention() -> _ArtifactRetentionPassResult:
    """Run one retention pass under a non-blocking exclusive lock and stamp it.

    Skips because retention is disabled or a protection source is unavailable
    still write the stamp. A busy lock returns without stamping.
    """

    with _try_exclusive_lock() as acquired:
        if not acquired:
            return _ArtifactRetentionPassResult(outcome="lock_busy", stamped=False)
        return _run_locked_pass()


def _run_locked_pass() -> _ArtifactRetentionPassResult:
    try:
        from sase.config import (
            get_artifact_retention_enabled,
            get_artifact_retention_keep_per_label,
            get_artifact_retention_max_age_days,
            get_artifact_retention_trash_grace_days,
        )
        from sase.core.artifact_file_explicit import read_artifact_file_index
        from sase.core.artifact_file_protection import collect_protected_artifact_ids
        from sase.core.artifact_file_retention import (
            RetentionPolicy,
            plan_artifact_file_retention,
        )
        from sase.core.artifact_file_trash import (
            purge_trashed_artifact_files,
            trash_artifact_files,
        )

        completed_at = datetime.now(UTC).isoformat()
        if not get_artifact_retention_enabled():
            return _stamp_result(
                _ArtifactRetentionPassResult(
                    outcome="disabled",
                    stamped=False,
                    completed_at=completed_at,
                )
            )

        now = datetime.now(UTC)
        completed_at = now.isoformat()
        protections = collect_protected_artifact_ids()
        if protections.sources_unavailable:
            sources = ", ".join(protections.sources_unavailable)
            print(
                "[artifacts] retention skipped: "
                f"protection sources unavailable: {sources}"
            )
            return _stamp_result(
                _ArtifactRetentionPassResult(
                    outcome="protection_unavailable",
                    stamped=False,
                    completed_at=completed_at,
                    sources_unavailable=tuple(protections.sources_unavailable),
                )
            )

        max_age_days = get_artifact_retention_max_age_days()
        policy = RetentionPolicy(
            now=now.isoformat(),
            keep_per_label=get_artifact_retention_keep_per_label(),
            before=None if max_age_days == 0 else f"{max_age_days}d",
            protected_ids=protections.ids,
        )
        plan = plan_artifact_file_retention(policy)
        rows_by_id = {row.id: row for row in read_artifact_file_index()}
        selected_rows = []
        missing_rows = 0
        for item in plan.selected:
            row = rows_by_id.get(item.id)
            if row is None:
                missing_rows += 1
            else:
                selected_rows.append(row)
        trashed = trash_artifact_files(
            selected_rows,
            reason="retention",
            now=policy.now,
        )
        purge_cutoff = (
            now - timedelta(days=get_artifact_retention_trash_grace_days())
        ).isoformat()
        purged = purge_trashed_artifact_files(before=purge_cutoff)
        missing_note = (
            f", skipped {missing_rows} disappeared rows" if missing_rows else ""
        )
        print(
            "[artifacts] retention: "
            f"trashed {trashed.rows_trashed} rows, "
            f"reclaimed {trashed.bytes_reclaimed} bytes, "
            f"purged {len(purged.purged_entry_ids)} trash entries"
            f"{missing_note}"
        )
        return _stamp_result(
            _ArtifactRetentionPassResult(
                outcome="enforced",
                stamped=False,
                completed_at=completed_at,
                rows_trashed=trashed.rows_trashed,
                bytes_reclaimed=trashed.bytes_reclaimed,
                purged_entries=len(purged.purged_entry_ids),
                missing_rows=missing_rows,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[artifacts] retention failed: {exc}")
        return _stamp_result(
            _ArtifactRetentionPassResult(
                outcome="failed",
                stamped=False,
                completed_at=datetime.now(UTC).isoformat(),
                error=str(exc),
            )
        )


def _stamp_result(
    result: _ArtifactRetentionPassResult,
) -> _ArtifactRetentionPassResult:
    completed_at = result.completed_at or datetime.now(UTC).isoformat()
    payload: dict[str, object] = {
        "completed_at": completed_at,
        "outcome": result.outcome,
        "rows_trashed": result.rows_trashed,
        "bytes_reclaimed": result.bytes_reclaimed,
        "purged_entries": result.purged_entries,
        "missing_rows": result.missing_rows,
    }
    if result.sources_unavailable:
        payload["sources_unavailable"] = list(result.sources_unavailable)
    if result.error:
        payload["error"] = result.error
    write_json_marker_atomic(_artifact_retention_stamp_path(), payload)
    return _ArtifactRetentionPassResult(
        outcome=result.outcome,
        stamped=True,
        completed_at=completed_at,
        rows_trashed=result.rows_trashed,
        bytes_reclaimed=result.bytes_reclaimed,
        purged_entries=result.purged_entries,
        missing_rows=result.missing_rows,
        sources_unavailable=result.sources_unavailable,
        error=result.error,
    )


@contextmanager
def _try_exclusive_lock() -> Iterator[bool]:
    lock_path = _artifact_retention_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if _is_lock_unavailable(exc):
                yield False
                return
            raise
        try:
            yield True
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _is_lock_unavailable(exc: OSError) -> bool:
    return isinstance(exc, BlockingIOError) or exc.errno in {
        errno.EACCES,
        errno.EAGAIN,
    }


def _parse_completed_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


__all__ = [
    "enforce_artifact_retention",
    "maybe_enforce_artifact_retention",
]
