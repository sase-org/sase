"""Compatibility facade for unread completed-agent helpers."""

from __future__ import annotations

from ._unread_navigation import AgentUnreadNavigationMixin


class AgentUnreadMixin(AgentUnreadNavigationMixin):
    """Aggregate unread state, candidate discovery, and navigation helpers."""


__all__ = ["AgentUnreadMixin"]
