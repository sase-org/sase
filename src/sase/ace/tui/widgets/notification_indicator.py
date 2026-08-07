"""Persistent notification indicator widget for the ace TUI."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import Static

if TYPE_CHECKING:
    from sase.ace.tui.modals.notification_modal_tags import NotificationTagTab

# Separator between per-tab chips: dim enough to read as punctuation rather
# than as another count.
_CHIP_SEPARATOR_STYLE = "#3A3A3A"

# The synthetic tab keys this widget special-cases. Spelled here rather than
# imported at module scope because ``widgets/__init__`` is loaded from inside
# the modals package's own import, and reaching back into it would cycle.
SNOOZED_TAB_KEY = "__snoozed__"
MUTED_TAB_KEY = "__muted__"


class NotificationIndicator(Static):
    """Always-visible per-tab notification badge in the top bar.

    The badge renders one colored count per notification-panel tab, in the
    panel's own tab order, so the leftmost chip is the leftmost tab and the
    colors are the ones the panel teaches. Snoozed is the one special case:
    it collapses to a dim ``<N>z`` when nothing else is pending and
    contributes no chip at all when anything else is. Beyond
    ``ace.notification_indicator_max_counts`` chips the remainder collapses
    into a dim ``+K``.

    Hovering reveals a per-tab briefing with the oldest activity in each tab
    and the next snooze wake; clicking opens the notification modal.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(()), **kwargs)
        self._tabs: tuple[NotificationTagTab, ...] = ()
        self.tooltip = self._build_tooltip(())

    def set_tabs(self, tabs: Sequence[NotificationTagTab]) -> None:
        """Update the per-tab counts driving the indicator.

        Args:
            tabs: The notification-panel tabs in panel order, exactly as the
                snapshot carries them. Empty tabs are dropped, so a tab that
                drains away stops rendering a chip.
        """
        resolved = tuple(tab for tab in tabs if tab.count > 0)
        if resolved == self._tabs:
            return
        self._tabs = resolved
        self.tooltip = self._build_tooltip(resolved)
        if self.is_mounted:
            self.update(self._build_content(resolved))

    async def on_click(self) -> None:
        """Open the notification modal, same as the ``show_notifications`` key."""
        await self.app.run_action("show_notifications")

    @staticmethod
    def _build_content(tabs: Sequence[NotificationTagTab]) -> Text:
        """Build the badge text: one colored count per visible tab."""
        from .notification_tab_style import (
            notification_indicator_max_counts,
            resolve_notification_tab_color,
        )

        visible = [tab for tab in tabs if tab.count > 0]
        if not visible:
            return Text(" ✉ 0 ", style="dim")

        snoozed = [tab for tab in visible if tab.tag == SNOOZED_TAB_KEY]
        others = [tab for tab in visible if tab.tag != SNOOZED_TAB_KEY]

        text = Text(" ✉ ", style="dim")
        if not others:
            # Nothing needs an answer, so the deferred backlog is worth the
            # badge — spelled with a ``z`` so it never reads as actionable.
            total = sum(tab.count for tab in snoozed)
            color = resolve_notification_tab_color(snoozed[0])
            text.append(f"{total}z", style=f"dim {color}")
            text.append(" ", style="dim")
            return text

        shown = others[: max(1, notification_indicator_max_counts())]
        for index, tab in enumerate(shown):
            if index:
                text.append("·", style=_CHIP_SEPARATOR_STYLE)
            text.append(
                str(tab.count),
                style=f"bold {resolve_notification_tab_color(tab)}",
            )
        suppressed = len(others) - len(shown)
        if suppressed:
            text.append("·", style=_CHIP_SEPARATOR_STYLE)
            text.append(f"+{suppressed}", style="dim")
        text.append(" ", style="dim")
        return text

    @staticmethod
    def _build_tooltip(tabs: Sequence[NotificationTagTab]) -> Text:
        """Build the hover briefing: one line per tab, oldest activity first."""
        from .notification_tab_style import (
            notification_tab_label,
            resolve_notification_tab_color,
        )

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
        width = max(len(label) for label in labels.values())
        for tab in visible:
            text.append(" ")
            text.append(
                labels[tab.tag].ljust(width),
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
    from sase.notifications.models import format_relative_time, format_relative_until

    if tab.tag == SNOOZED_TAB_KEY:
        if tab.next_wake_at:
            return f"next wakes in {format_relative_until(tab.next_wake_at)}"
        return ""
    if tab.tag == MUTED_TAB_KEY:
        # A muted backlog has no deadline, so a timestamp would only add noise.
        return ""
    if tab.oldest_activity_at:
        return f"oldest {format_relative_time(tab.oldest_activity_at)}"
    return ""
