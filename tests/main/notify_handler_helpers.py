"""Shared builders for ``sase notify`` handler tests."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

from sase.core.time import get_timezone
from sase.notifications.models import Notification


def timestamp(minutes_ago: int) -> str:
    return (datetime.now(get_timezone()) - timedelta(minutes=minutes_ago)).isoformat()


def make_notification(
    notification_id: str,
    *,
    minutes_ago: int = 0,
    sender: str = "test",
    icon: str | None = None,
    color: str | None = None,
    notes: list[str] | None = None,
    files: list[str] | None = None,
    tags: list[str] | None = None,
    action: str | None = None,
    action_data: dict[str, str] | None = None,
    read: bool = False,
    dismissed: bool = False,
    resurfaced_at: str | None = None,
) -> Notification:
    return Notification(
        id=notification_id,
        timestamp=timestamp(minutes_ago),
        sender=sender,
        icon=icon,
        color=color,
        notes=notes or [],
        files=files or [],
        tags=tags or [],
        action=action,
        action_data=action_data or {},
        read=read,
        dismissed=dismissed,
        resurfaced_at=resurfaced_at,
    )


def list_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "json": False,
        "limit": 20,
        "query": None,
        "sender": None,
        "unread": False,
        "all": False,
        "tag": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def show_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {"id": "target", "format": "markdown"}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)
