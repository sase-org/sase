"""Minimal healer notifications (phase ``healer``).

Three call sites, stable across the ``episode-notify`` upgrade:

- :func:`publish_relaunch`: a plain upsert with the episode sender and
  dedup key.
- :func:`publish_escalation`: a loud error-severity row for declines,
  post-provider deaths, re-broken replacements, and the storm breaker.
- :func:`resurface_failure`: makes the original failure notification loud
  again, or rebuilds the standard failure notification from ``done.json``
  and ``error_report.md`` when it is missing, with one explanatory note.

Phase ``episode-notify`` replaces the bodies with the live-report
experience; the call sites stay.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

SENDER = "agent.auto-restart"
ICON = "↻"
COLOR = "#FFAF5F"


def episode_dedup_key(episode_id: str) -> str:
    """Return the upsert dedup key for one update episode."""
    return f"agent-auto-restart:{episode_id}"


def _timestamp() -> str:
    from datetime import datetime

    from sase.core.time import get_timezone

    return datetime.now(get_timezone()).isoformat()


def publish_relaunch(
    *,
    episode_id: str,
    agent_name: str,
    update_ref: str,
    reason_text: str,
    evidence_files: list[str] | None = None,
) -> Any:
    """Upsert the episode row for one relaunch (plus-one within it)."""
    from sase.notifications.models import Notification, normalize_notification_tags
    from sase.notifications.store import upsert_notification

    first = f"Restarted {agent_name} after sase update {update_ref}"
    notification = Notification(
        id=str(uuid4()),
        timestamp=_timestamp(),
        sender=SENDER,
        icon=ICON,
        color=COLOR,
        notes=[first, reason_text],
        files=list(evidence_files or []),
        tags=normalize_notification_tags(
            ["sase-update", "auto-restart", "update-skew"]
        ),
        action="ViewReport",
        dedup_key=episode_dedup_key(episode_id),
    )
    return upsert_notification(notification, plus_one_note=f"Restarted {agent_name}")


def publish_escalation(
    *,
    agent_name: str,
    title: str,
    detail: str,
    episode_id: str | None = None,
) -> Any:
    """Post one loud error-severity escalation for a declined restart."""
    from sase.notifications.models import Notification, normalize_notification_tags
    from sase.notifications.store import upsert_notification

    notification = Notification(
        id=str(uuid4()),
        timestamp=_timestamp(),
        sender=SENDER,
        icon=ICON,
        color=COLOR,
        notes=[title, detail],
        tags=normalize_notification_tags(["sase-update", "auto-restart", "error"]),
        dedup_key=(
            f"{episode_dedup_key(episode_id)}:{agent_name}"
            if episode_id
            else f"agent-auto-restart:{agent_name}:declined"
        ),
    )
    return upsert_notification(notification)


def resurface_failure(
    *,
    agent_name: str,
    reason_text: str,
    artifacts_dir: str | None = None,
) -> Any:
    """Make the original failure visible again with one explanatory note.

    Rebuilds the standard failure notification from ``done.json`` and
    ``error_report.md`` when the row is missing; never swallows the failure.
    """
    from sase.notifications.models import Notification, normalize_notification_tags
    from sase.notifications.store import upsert_notification

    notes = [f"{agent_name} failed and was not restarted automatically."]
    if reason_text:
        notes.append(reason_text)
    files: list[str] = []
    if artifacts_dir:
        from pathlib import Path

        report = Path(artifacts_dir) / "error_report.md"
        try:
            if report.is_file():
                files.append(str(report))
        except OSError:
            pass
    notification = Notification(
        id=str(uuid4()),
        timestamp=_timestamp(),
        sender="user-agent",
        notes=notes,
        files=files,
        tags=normalize_notification_tags(["auto-restart", "resurfaced"]),
        action="ViewErrorReport",
        dedup_key=f"agent-auto-restart-resurfaced:{agent_name}",
    )
    return upsert_notification(notification)


__all__ = [
    "COLOR",
    "ICON",
    "SENDER",
    "episode_dedup_key",
    "publish_escalation",
    "publish_relaunch",
    "resurface_failure",
]
