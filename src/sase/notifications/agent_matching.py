"""Helpers for matching notifications to loaded agent rows."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from sase.notifications.models import Notification


class _AgentLike(Protocol):
    cl_name: str
    project_file: str
    raw_suffix: str | None
    agent_name: str | None
    workspace_dir: str | None


def _notification_agent_timestamps(notification: Notification) -> frozenset[str]:
    """Return normalized phase/root timestamps carried by a notification."""
    timestamps: set[str] = set()
    for key in ("agent_timestamp", "agent_root_timestamp"):
        timestamp = _normalize_timestamp(notification.action_data.get(key))
        if timestamp:
            timestamps.add(timestamp)
    return frozenset(timestamps)


def agent_matches_notification_identity(
    agent: _AgentLike, notification: Notification, cl_name: str | None = None
) -> bool:
    """Return True when an agent row matches notification routing fields."""
    action_data = notification.action_data
    expected_cl_name = _clean(cl_name) or _clean(action_data.get("agent_cl_name"))
    expected_agent_name = _clean(action_data.get("agent_name"))
    timestamps = _notification_agent_timestamps(notification)

    if timestamps:
        agent_timestamp = _normalize_timestamp(getattr(agent, "raw_suffix", None))
        if agent_timestamp not in timestamps:
            return False
        return _identity_matches(
            agent,
            expected_cl_name=expected_cl_name,
            expected_agent_name=expected_agent_name,
        )

    return _conservative_timestampless_match(
        agent,
        notification,
        expected_cl_name=expected_cl_name,
        expected_agent_name=expected_agent_name,
    )


def notification_matches_any_agent(
    notification: Notification, agents: list[_AgentLike] | tuple[_AgentLike, ...]
) -> bool:
    """Return True when any loaded agent row matches a notification."""
    return any(
        agent_matches_notification_identity(agent, notification) for agent in agents
    )


def _identity_matches(
    agent: _AgentLike, *, expected_cl_name: str | None, expected_agent_name: str | None
) -> bool:
    if expected_cl_name and _clean(getattr(agent, "cl_name", None)) == expected_cl_name:
        return True
    if (
        expected_agent_name
        and _clean(getattr(agent, "agent_name", None)) == expected_agent_name
    ):
        return True
    return False


def _conservative_timestampless_match(
    agent: _AgentLike,
    notification: Notification,
    *,
    expected_cl_name: str | None,
    expected_agent_name: str | None,
) -> bool:
    if not expected_agent_name:
        return False
    if _clean(getattr(agent, "agent_name", None)) != expected_agent_name:
        return False
    if expected_cl_name and _clean(getattr(agent, "cl_name", None)) == expected_cl_name:
        return True

    action_data = notification.action_data
    if _same_path(
        action_data.get("agent_project_file"), getattr(agent, "project_file", None)
    ):
        return True
    if _same_path(
        action_data.get("project_dir"), getattr(agent, "workspace_dir", None)
    ):
        return True
    return False


def _normalize_timestamp(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    from sase.ace.tui.models._timestamps import normalize_to_14_digit

    return normalize_to_14_digit(value.strip())


def _clean(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _same_path(left: object, right: object) -> bool:
    left_text = _clean(left)
    right_text = _clean(right)
    if not left_text or not right_text:
        return False
    left_path = Path(left_text).expanduser().resolve(strict=False)
    right_path = Path(right_text).expanduser().resolve(strict=False)
    return left_path == right_path
