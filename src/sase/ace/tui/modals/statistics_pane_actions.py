"""Keymap actions and pointer input for the Admin Center Statistics pane."""

from __future__ import annotations

from .statistics_pane_actions_filters import StatisticsPaneActionsFiltersMixin


class StatisticsPaneActionsMixin(StatisticsPaneActionsFiltersMixin):
    """Drive Statistics pane state from keymap actions and pointer input."""


__all__ = ["StatisticsPaneActionsMixin"]
