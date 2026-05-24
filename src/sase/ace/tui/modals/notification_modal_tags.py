"""Tag tab helpers for the notification modal."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.widgets import Static

from sase.notifications import Notification


@dataclass(frozen=True)
class NotificationTagTab:
    """One notification tag tab in display order."""

    tag: str | None
    label: str
    count: int


def notification_display_tags(notification: Notification) -> list[str]:
    """Return displayable tags for one notification, deduped in stored order."""
    tags: list[str] = []
    seen: set[str] = set()
    for raw_tag in getattr(notification, "tags", []) or []:
        if not isinstance(raw_tag, str):
            continue
        tag = raw_tag.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags


def notification_has_tag(notification: Notification, tag: str) -> bool:
    """Return whether a notification belongs in a tag tab."""
    return tag in notification_display_tags(notification)


def build_notification_tag_tabs(
    notifications: list[Notification],
) -> list[NotificationTagTab]:
    """Build modal tag tabs: All, pinned done, then remaining tags alphabetically."""
    counts: Counter[str] = Counter()
    for notification in notifications:
        for tag in notification_display_tags(notification):
            counts[tag] += 1

    ordered_tags: list[str] = []
    if "done" in counts:
        ordered_tags.append("done")
    ordered_tags.extend(sorted(tag for tag in counts if tag != "done"))

    return [
        NotificationTagTab(None, "All", len(notifications)),
        *[NotificationTagTab(tag, tag, counts[tag]) for tag in ordered_tags],
    ]


def shorten_notification_tag(tag: str, *, max_width: int = 18) -> str:
    """Return a compact tag label that cannot dominate a row or tab."""
    if len(tag) <= max_width:
        return tag
    return f"{tag[: max_width - 3]}..."


class NotificationTagStrip(Static):
    """Clickable one-line tag tab strip for NotificationModal."""

    class TabClicked(Message):
        """Message emitted when a tag tab is clicked."""

        def __init__(self, tag: str | None) -> None:
            super().__init__()
            self.tag = tag

    def __init__(
        self,
        tabs: list[NotificationTagTab],
        active_tag: str | None,
        **kwargs: Any,
    ) -> None:
        self._tabs = list(tabs)
        self._active_tag = active_tag
        self._tab_ranges: dict[str | None, tuple[int, int]] = {}
        super().__init__(self._build_content(), **kwargs)

    def set_tabs(
        self,
        tabs: list[NotificationTagTab],
        active_tag: str | None,
    ) -> None:
        """Refresh tabs and active state."""
        self._tabs = list(tabs)
        self._active_tag = active_tag
        self.update(self._build_content())

    def _build_content(self) -> Text:
        """Build the rich tag strip content and click ranges."""
        text = Text()
        self._tab_ranges.clear()

        for index, tab in enumerate(self._tabs):
            if index > 0:
                text.append(" | ", style="#444444")

            is_active = tab.tag == self._active_tag
            style = "bold #00D7AF" if is_active else "#888888"
            count_style = "bold #87D7FF" if is_active else "#666666"
            start = len(text.plain)
            text.append(" ", style=style)
            text.append(shorten_notification_tag(tab.label), style=style)
            text.append(" ", style=style)
            text.append(str(tab.count), style=count_style)
            text.append(" ", style=style)
            self._tab_ranges[tab.tag] = (start, len(text.plain))

        return text

    def on_click(self, event: Click) -> None:
        """Switch to a clicked tag tab."""
        for tag, (start, end) in self._tab_ranges.items():
            if start <= event.x < end:
                if tag != self._active_tag:
                    self.post_message(self.TabClicked(tag))
                return
