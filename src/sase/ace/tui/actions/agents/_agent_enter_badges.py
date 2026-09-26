"""Badges, ages, and subtitles for Enter targets."""

from __future__ import annotations

from datetime import datetime, UTC
from typing import TYPE_CHECKING

from sase.core.time import local_now, parse_local
from sase.gate_turn.status import gate_status_pair, gate_status_style

if TYPE_CHECKING:
    from ...models import Agent
    from sase.notifications import Notification


def _compact_age(age_seconds: float | None) -> str | None:
    if age_seconds is None or age_seconds < 0:
        return None
    try:
        from ...models.agent_time import format_compact_duration

        return format_compact_duration(age_seconds)
    except Exception:
        minutes = int(age_seconds // 60)
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 48:
            return f"{hours}h"
        return f"{hours // 24}d"


def gate_badge(status: str | None, age_seconds: float | None) -> str | None:
    normalized = (status or "").strip().upper() or "GATE"
    age = _compact_age(age_seconds)
    return f"{normalized} · {age}" if age else normalized


def notification_age_seconds(notification: Notification) -> float | None:
    parsed = parse_local(notification.timestamp)
    if parsed is None:
        return None
    delta = datetime.now(UTC) - parsed
    return max(0.0, delta.total_seconds())


def row_age_seconds(row: Agent) -> float | None:
    start = getattr(row, "start_time", None)
    if not isinstance(start, datetime):
        return None
    now = local_now() if start.tzinfo is None else datetime.now(UTC)
    try:
        return max(0.0, (now - start).total_seconds())
    except TypeError:
        return None


def gate_badge_style(row: Agent) -> str | None:
    try:
        pair = gate_status_pair(
            getattr(row, "gate_start_status", None),
            getattr(row, "gate_stop_status", None),
        )
        return gate_status_style(
            pair,
            gate_state=getattr(row, "gate_state", None),
            accent=getattr(row, "gate_accent", None),
        )
    except Exception:
        return None


def notification_gate_detail(notification: Notification) -> str | None:
    if notification.files:
        name = str(notification.files[0]).strip()
        if name:
            return name.rsplit("/", 1)[-1]
    for key in ("title", "message", "plan_file"):
        value = notification.action_data.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            return text.rsplit("/", 1)[-1] if "/" in text else text
    return None


__all__ = [
    "_compact_age",
    "gate_badge",
    "gate_badge_style",
    "notification_age_seconds",
    "notification_gate_detail",
    "row_age_seconds",
]
