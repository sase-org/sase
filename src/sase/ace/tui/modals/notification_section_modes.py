"""Per-process notification section mode state."""

from __future__ import annotations

from .notification_sections import (
    NotificationSectionStrategy,
    resolve_tab_section_strategy,
)

GROUPED_MODE = "grouped"
RECENT_MODE = "recent"


class NotificationSectionModes:
    """Mutable per-tab grouped/recent choices for one ACE process."""

    def __init__(self) -> None:
        self._modes: dict[str, str] = {}

    def mode_for(self, config_key: str) -> str:
        """Return the effective mode for *config_key*."""
        explicit = self._modes.get(config_key)
        if explicit is not None:
            return explicit
        if resolve_tab_section_strategy(config_key) is not None:
            return GROUPED_MODE
        return RECENT_MODE

    def toggle(self, config_key: str) -> str:
        """Toggle one tab between grouped and recent, returning the new mode."""
        next_mode = (
            RECENT_MODE if self.mode_for(config_key) == GROUPED_MODE else GROUPED_MODE
        )
        self._modes[config_key] = next_mode
        return next_mode

    def strategy_for(self, config_key: str) -> NotificationSectionStrategy | None:
        """Return the active strategy when the tab is currently grouped."""
        if self.mode_for(config_key) != GROUPED_MODE:
            return None
        return resolve_tab_section_strategy(config_key)


__all__ = ["GROUPED_MODE", "RECENT_MODE", "NotificationSectionModes"]
