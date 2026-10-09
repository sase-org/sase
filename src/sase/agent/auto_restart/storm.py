"""Storm breaker: pause auto-restart when the volume looks like a real bug.

When launches would exceed ``storm_max_per_episode`` in one update episode
or ``storm_max_per_30m`` in any rolling 30 minutes, the breaker marks
``state.json`` paused, the healer declines the remainder with ``paused``,
and one storm escalation goes out. ``resume`` clears the pause.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.auto_restart.ledger import StoredLedgerRecord, auto_restart_root

STATE_FILENAME = "state.json"
ROLLING_WINDOW_SECONDS = 30 * 60


@dataclass(frozen=True)
class StormDecision:
    """Whether one more launch fits inside the storm budget."""

    allowed: bool
    reason: str


def state_path() -> Path:
    """Return the storm-breaker state path."""
    return auto_restart_root() / STATE_FILENAME


def is_paused() -> tuple[bool, dict[str, Any]]:
    """Return ``(paused, state)`` from ``state.json`` (missing means open)."""
    import json

    try:
        payload = json.loads(state_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError):
        return False, {}
    except (OSError, ValueError):
        return False, {}
    if not isinstance(payload, dict):
        return False, {}
    return bool(payload.get("paused", False)), payload


def clear_pause() -> dict[str, Any]:
    """Re-arm after the storm breaker trips; returns the written state."""
    from sase.notification_gates.durability import atomic_write_json

    state: dict[str, Any] = {
        "schema_version": 1,
        "paused": False,
        "paused_at": None,
        "paused_reason": None,
        "paused_episode": None,
        "resumed_at": time.time(),
    }
    try:
        atomic_write_json(state_path(), state)
    except OSError:
        pass
    return state


def trip_pause(*, reason: str, episode: str | None = None) -> dict[str, Any]:
    """Pause the feature and record why; returns the written state."""
    from sase.notification_gates.durability import atomic_write_json

    state: dict[str, Any] = {
        "schema_version": 1,
        "paused": True,
        "paused_at": time.time(),
        "paused_reason": reason,
        "paused_episode": episode,
        "resumed_at": None,
    }
    try:
        atomic_write_json(state_path(), state)
    except OSError:
        pass
    return state


def storm_check(
    records: list[StoredLedgerRecord],
    *,
    episode_id: str | None,
    max_per_episode: int,
    max_per_30m: int,
    now: float | None = None,
) -> StormDecision:
    """Return whether one more launch fits inside the storm budget.

    Only records that actually launched count: ``launched`` (and later
    settled) states. Claims, deferrals, and declines are not launches.
    """
    at = time.time() if now is None else now
    launched = [
        r
        for r in records
        if r.record.state in ("launched", "settled_ok", "settled_failed")
    ]
    windowed = [r for r in launched if _launched_at(r) >= at - ROLLING_WINDOW_SECONDS]
    if len(windowed) >= max_per_30m:
        return StormDecision(
            allowed=False,
            reason=(
                f"{len(windowed)} automatic launches in the last 30 minutes "
                "(limit "
                f"{max_per_30m}) — this looks like a real bug, not an update race"
            ),
        )
    if episode_id:
        episodic = [r for r in launched if r.record.episode_id == episode_id]
        if len(episodic) >= max_per_episode:
            return StormDecision(
                allowed=False,
                reason=(
                    f"{len(episodic)} automatic launches in episode {episode_id} "
                    f"(limit {max_per_episode}) — this looks like a real bug, "
                    "not an update race"
                ),
            )
    return StormDecision(allowed=True, reason="within storm budget")


def _launched_at(stored: StoredLedgerRecord) -> float:
    for entry in stored.record.history:
        if entry.state in ("launched", "settled_ok", "settled_failed") and entry.at:
            try:
                from datetime import datetime

                return datetime.fromisoformat(entry.at).timestamp()
            except (ValueError, TypeError):
                continue
    claimed = stored.record.claimed_at
    if claimed:
        try:
            from datetime import datetime

            return datetime.fromisoformat(claimed).timestamp()
        except (ValueError, TypeError):
            pass
    return 0.0


__all__ = [
    "ROLLING_WINDOW_SECONDS",
    "STATE_FILENAME",
    "StormDecision",
    "clear_pause",
    "is_paused",
    "state_path",
    "storm_check",
    "trip_pause",
]
