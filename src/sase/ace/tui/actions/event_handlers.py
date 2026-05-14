"""Event handler mixin for the ace TUI app."""

from __future__ import annotations

from ._event_activity import EventActivityMixin
from ._event_base import TabName
from ._event_keyboard import EventKeyboardMixin
from ._event_refresh import (
    DAEMON_REFRESH_EVENT_BATCH_LIMIT,
    DAEMON_REFRESH_MAX_EVENTS,
    FULL_SANITY_REFRESH_SECONDS,
    PROMPT_INPUT_DEFER_SECONDS,
    EventRefreshMixin,
)
from ._event_widgets import EventWidgetHandlersMixin


class EventHandlersMixin(
    EventWidgetHandlersMixin,
    EventKeyboardMixin,
    EventActivityMixin,
    EventRefreshMixin,
):
    """Mixin combining ACE TUI event handlers and timer callbacks."""


__all__ = [
    "DAEMON_REFRESH_EVENT_BATCH_LIMIT",
    "DAEMON_REFRESH_MAX_EVENTS",
    "FULL_SANITY_REFRESH_SECONDS",
    "PROMPT_INPUT_DEFER_SECONDS",
    "EventHandlersMixin",
    "TabName",
]
