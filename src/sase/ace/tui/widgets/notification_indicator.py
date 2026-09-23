"""Persistent notification indicator widget for sase's TUI."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from rich.cells import cell_len
from rich.text import Text

from .top_bar_group import TopBarGroup

if TYPE_CHECKING:
    from sase.ace.tui.modals.notification_modal_tags import NotificationTagTab

# The synthetic tab keys this widget special-cases. Spelled here rather than
# imported at module scope because ``widgets/__init__`` is loaded from inside
# the modals package's own import, and reaching back into it would cycle.
SNOOZED_TAB_KEY = "__snoozed__"
MUTED_TAB_KEY = "__muted__"


class NotificationIndicator(TopBarGroup):
    """Always-visible per-tab notification badge in the top bar.

    Renders as ``inbox: <chips>`` with one ``<icon><count>`` chip per
    notification-panel tab, in the panel's own tab order, so the leftmost
    chip is the leftmost tab and the icons and colors are the ones the
    panel teaches. Chips are joined by one space with no separator glyph;
    the ``·`` separates groups, not tab chips. The empty state is a dim
    ``0``; a snoozed-only backlog collapses to a dim ``<icon><N>``.
    Beyond ``ace.notification_indicator_max_counts`` chips the remainder
    collapses into a dim ``+K``.

    Hovering reveals a per-tab briefing with the oldest activity in each tab
    and the next snooze wake; clicking opens the notification modal.
    """

    GROUP_LABEL = "inbox"
    CLICK_ACTION = "show_notifications"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tabs: tuple[NotificationTagTab, ...] = ()
        self._set_body(self._build_content(()))
        self.tooltip = self._build_tooltip(())

    def set_tabs(self, tabs: Sequence[NotificationTagTab]) -> None:
        """Update the per-tab counts driving the indicator.

        Args:
            tabs: The notification-panel tabs in panel order, exactly as the
                snapshot carries them. Empty tabs are omitted at render time,
                so a tab that drains away stops rendering a chip.
        """
        resolved = tuple(tabs)
        if resolved == self._tabs:
            return
        self._tabs = resolved
        self._set_body(self._build_content(resolved))
        tooltip = self._build_tooltip(resolved)
        if self.tooltip != tooltip:
            self.tooltip = tooltip

    @staticmethod
    def _build_content(tabs: Sequence[NotificationTagTab]) -> Text:
        """Build the badge body: one colored ``<icon><count>`` per visible tab."""
        from .notification_tab_style import (
            notification_indicator_max_counts,
            resolve_notification_tab_color,
            resolve_notification_tab_icons,
        )

        icons = resolve_notification_tab_icons(tabs)
        visible = [tab for tab in tabs if tab.count > 0]
        if not visible:
            return Text("0", style="dim")

        snoozed = [tab for tab in visible if tab.tag == SNOOZED_TAB_KEY]
        others = [tab for tab in visible if tab.tag != SNOOZED_TAB_KEY]

        if not others:
            # Nothing needs an answer, so the deferred backlog is worth the
            # badge — the moon glyph keeps it from reading as actionable.
            total = sum(tab.count for tab in snoozed)
            color = resolve_notification_tab_color(snoozed[0])
            icon = icons[snoozed[0].tag]
            return Text(f"{icon}{total}", style=f"dim {color}")

        text = Text()
        shown = others[: max(1, notification_indicator_max_counts())]
        for index, tab in enumerate(shown):
            if index:
                text.append(" ", style="dim")
            icon = icons[tab.tag]
            text.append(
                f"{icon}{tab.count}",
                style=f"bold {resolve_notification_tab_color(tab)}",
            )
        suppressed = len(others) - len(shown)
        if suppressed:
            text.append(f" +{suppressed}", style="dim")
        return text

    @staticmethod
    def _build_tooltip(tabs: Sequence[NotificationTagTab]) -> Text:
        """Build the hover briefing: one line per tab, oldest activity first."""
        from .notification_tab_style import (
            notification_tab_label,
            resolve_notification_tab_color,
            resolve_notification_tab_icons,
        )

        icons = resolve_notification_tab_icons(tabs)
        visible = [tab for tab in tabs if tab.count > 0]
        if not visible:
            return Text("No unread notifications", style="dim")

        unread_tabs = [
            tab for tab in visible if tab.tag not in (SNOOZED_TAB_KEY, MUTED_TAB_KEY)
        ]
        unread = sum(tab.count for tab in unread_tabs)

        text = Text()
        if unread:
            plural = "" if len(unread_tabs) == 1 else "s"
            text.append(f"{unread} unread · {len(unread_tabs)} tab{plural}\n")
        else:
            text.append("No unread notifications\n")

        labels = {tab.tag: notification_tab_label(tab) for tab in visible}
        # Both columns are measured in terminal cells, not characters: a
        # two-cell icon or a non-ASCII tag label would otherwise skew every
        # line below it.
        icon_width = max(cell_len(icon) for icon in icons.values())
        width = max(cell_len(label) for label in labels.values())
        for tab in visible:
            icon = icons[tab.tag]
            label = labels[tab.tag]
            text.append(" ")
            text.append(
                f"{icon}{' ' * (icon_width - cell_len(icon))} "
                f"{label}{' ' * (width - cell_len(label))}",
                style=resolve_notification_tab_color(tab),
            )
            text.append(f"  {tab.count}")
            detail = _tab_detail(tab)
            if detail:
                text.append(f"   {detail}", style="dim")
            text.append("\n")
        text.append("Click to open the notification panel", style="dim")
        return text


def _tab_detail(tab: NotificationTagTab) -> str:
    """Return the trailing time phrase for one tooltip line, if any."""
    from sase.ace.tui.widgets.notification_tab_style import (
        default_notification_tab_priority,
        notification_tab_priority_mark,
        resolve_notification_tab_priority,
    )
    from sase.notifications.models import format_relative_time, format_relative_until

    if tab.tag == SNOOZED_TAB_KEY:
        detail = (
            f"next wakes in {format_relative_until(tab.next_wake_at)}"
            if tab.next_wake_at
            else ""
        )
    elif tab.tag == MUTED_TAB_KEY:
        # A muted backlog has no deadline, so a timestamp would only add noise.
        detail = ""
    elif tab.oldest_activity_at:
        detail = f"oldest {format_relative_time(tab.oldest_activity_at)}"
    else:
        detail = ""
    effective = resolve_notification_tab_priority(tab)
    if effective == default_notification_tab_priority(tab):
        return detail
    mark = notification_tab_priority_mark(tab)
    if mark is None:
        return detail
    fragment = f"{mark.glyph} priority {effective}"
    if detail:
        return f"{detail} · {fragment}"
    return fragment
