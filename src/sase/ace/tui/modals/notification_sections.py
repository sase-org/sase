"""Notification row grouping strategies for modal tabs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sase.ace.tui.widgets.notification_tab_style import (
    resolve_notification_tab_grouping,
)
from sase.notifications import Notification

RECENT_STRATEGY_ID = "recent"


@dataclass(frozen=True)
class NotificationSection:
    """One section header emitted by a notification grouping strategy."""

    key: str
    label: str
    glyph: str
    color: str
    order: tuple[int, int, str]


@dataclass(frozen=True)
class NotificationSectionStrategy:
    """Registered notification grouping strategy."""

    id: str
    display_name: str
    section_for: Callable[[Notification], NotificationSection]


def _bead_type_strategy() -> NotificationSectionStrategy:
    from .notification_sections_bead import bead_type_section_for

    return NotificationSectionStrategy(
        id="bead_type",
        display_name="type",
        section_for=bead_type_section_for,
    )


NOTIFICATION_SECTION_STRATEGIES: dict[str, NotificationSectionStrategy] = {
    "bead_type": _bead_type_strategy(),
}
DEFAULT_TAB_STRATEGY_IDS: dict[str, str] = {"beads": "bead_type"}


def resolve_tab_section_strategy(
    config_key: str,
) -> NotificationSectionStrategy | None:
    """Return the effective section strategy for one tab config key."""
    configured = resolve_notification_tab_grouping(config_key)
    if configured == RECENT_STRATEGY_ID:
        return None
    strategy_id = configured or DEFAULT_TAB_STRATEGY_IDS.get(config_key, "")
    return NOTIFICATION_SECTION_STRATEGIES.get(strategy_id)


def group_notifications[T](
    rows: Iterable[tuple[T, Notification]],
    strategy: NotificationSectionStrategy,
) -> list[tuple[NotificationSection, list[tuple[T, Notification]]]]:
    """Stable-partition notification rows into ordered non-empty sections."""
    buckets: dict[NotificationSection, list[tuple[T, Notification]]] = defaultdict(list)
    for row in rows:
        _key, notification = row
        buckets[strategy.section_for(notification)].append(row)
    return sorted(buckets.items(), key=lambda item: item[0].order)


__all__ = [
    "DEFAULT_TAB_STRATEGY_IDS",
    "NOTIFICATION_SECTION_STRATEGIES",
    "RECENT_STRATEGY_ID",
    "NotificationSection",
    "NotificationSectionStrategy",
    "group_notifications",
    "resolve_tab_section_strategy",
]
