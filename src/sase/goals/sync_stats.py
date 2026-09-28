"""Machine-local goal publish contention counters (sase-1bu publish-sync).

After each goal publish, the writer updates
``~/.sase/projects/<key>/goals-sync-stats.json``::

    {"schema_version": 1, "publishes": N, "push_retries": M,
     "rejected_after_max": K, "last_retry_at": "<iso>" | None}

``push_retries`` counts non-fast-forward rejections that were retried.
A missing or corrupt stats file reads as zeros and never fails a command.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GOALS_SYNC_STATS_SCHEMA_VERSION = 1


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def read_goals_sync_stats(stats_path: str | Path) -> dict[str, Any]:
    """Return the stats record; missing/corrupt reads as zeros."""
    empty: dict[str, Any] = {
        "schema_version": GOALS_SYNC_STATS_SCHEMA_VERSION,
        "publishes": 0,
        "push_retries": 0,
        "rejected_after_max": 0,
        "last_retry_at": None,
    }
    try:
        payload = json.loads(Path(stats_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(payload, dict):
        return empty

    def _count(key: str) -> int:
        try:
            return max(0, int(payload.get(key, 0)))
        except (TypeError, ValueError):
            return 0

    return {
        "schema_version": GOALS_SYNC_STATS_SCHEMA_VERSION,
        "publishes": _count("publishes"),
        "push_retries": _count("push_retries"),
        "rejected_after_max": _count("rejected_after_max"),
        "last_retry_at": payload.get("last_retry_at"),
    }


def record_goals_publish(
    stats_path: str | Path,
    *,
    push_attempts: int = 0,
    rejected_after_max: bool = False,
) -> dict[str, Any]:
    """Record one goal publish; return the updated stats record."""
    path = Path(stats_path)
    stats = read_goals_sync_stats(path)
    retries = max(0, int(push_attempts) - 1) if push_attempts > 1 else 0
    stats["publishes"] = int(stats["publishes"]) + 1
    if retries:
        stats["push_retries"] = int(stats["push_retries"]) + retries
        stats["last_retry_at"] = _utc_now_iso()
    if rejected_after_max:
        stats["rejected_after_max"] = int(stats["rejected_after_max"]) + 1
        if stats["last_retry_at"] is None:
            stats["last_retry_at"] = _utc_now_iso()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(stats, stream, indent=2, sort_keys=True)
                stream.write("\n")
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as exc:  # noqa: BLE001 - stats never fail a publish.
        logger.warning("goals sync-stats write failed for %s: %s", path, exc)
    return stats
