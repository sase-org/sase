"""Event handler mixin for sase's TUI app."""

from __future__ import annotations

from ._event_base import TabName
from ._event_countdown import EventCountdownMixin
from ._event_keyboard import EventKeyboardMixin
from ._event_refresh import (
    FULL_SANITY_REFRESH_SECONDS,
    PROMPT_INPUT_DEFER_SECONDS,
    EventRefreshMixin,
)
from ._event_widgets import EventWidgetHandlersMixin


class EventHandlersMixin(
    EventWidgetHandlersMixin,
    EventKeyboardMixin,
    EventCountdownMixin,
    EventRefreshMixin,
):
    """Mixin combining sase's TUI event handlers and timer callbacks."""


__all__ = [
    "FULL_SANITY_REFRESH_SECONDS",
    "PROMPT_INPUT_DEFER_SECONDS",
    "EventHandlersMixin",
    "TabName",
]
