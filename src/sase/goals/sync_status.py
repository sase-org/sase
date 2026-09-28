"""Honest freshness for goal ledgers (epic sase-1bu, phase publish-sync).

The watermark is the mtime of the hidden clone's
``.git/sase-bead-sync.integration`` marker, which
:func:`integrate_sdd_repository` touches on every successful integration.
Local mode reports ``local only`` and never fetches.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from sase.goals.store import GoalLedger

logger = logging.getLogger(__name__)


def goals_fetch_lock_path(ledger: GoalLedger) -> Path:
    """Return the single-flight fetch lock next to the projection."""
    return ledger.projection_path.with_name(f"{ledger.projection_path.name}.fetch.lock")


def _fetch_refreshing(lock_path: Path) -> bool:
    """Return True while another fetch worker holds the lock."""
    import fcntl

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(lock_path, "a+", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        logger.warning("goals fetch-lock probe failed for %s: %s", lock_path, exc)
        return False
    return False


def goal_sync_status(ledger: GoalLedger) -> dict[str, Any]:
    """Describe *ledger* freshness without touching the network."""
    from sase.goals.outbox import goals_outbox_pending

    if ledger.mode == "local":
        return {
            "mode": "local",
            "synced_at": None,
            "synced_ago_seconds": None,
            "unpublished": False,
            "refreshing": False,
            "reason": ledger.reason or "local only",
            **_stats_suffix(ledger),
        }
    synced_at: float | None = None
    try:
        synced_at = ledger.watermark_path.stat().st_mtime
    except OSError:
        synced_at = None
    now = time.time()
    lock_path = goals_fetch_lock_path(ledger)
    try:
        refreshing = _fetch_refreshing(lock_path)
    except Exception:  # noqa: BLE001 - freshness never fails a command.
        refreshing = False
    return {
        "mode": ledger.mode,
        "synced_at": synced_at,
        "synced_ago_seconds": (now - synced_at) if synced_at is not None else None,
        "unpublished": goals_outbox_pending(ledger.outbox_path),
        "refreshing": refreshing,
        **_stats_suffix(ledger),
    }


def _stats_suffix(ledger: GoalLedger) -> dict[str, Any]:
    from sase.core.paths import sase_projects_dir

    from sase.goals.sync_stats import read_goals_sync_stats

    stats_path = sase_projects_dir() / ledger.project / "goals-sync-stats.json"
    try:
        stats = read_goals_sync_stats(stats_path)
    except Exception:  # noqa: BLE001 - stats never fail a status read.
        stats = {
            "publishes": 0,
            "push_retries": 0,
            "rejected_after_max": 0,
            "last_retry_at": None,
        }
    return {
        "publishes": stats.get("publishes", 0),
        "push_retries": stats.get("push_retries", 0),
        "rejected_after_max": stats.get("rejected_after_max", 0),
        "last_retry_at": stats.get("last_retry_at"),
    }
