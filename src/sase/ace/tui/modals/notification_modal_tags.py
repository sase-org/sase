"""Tag and panel tab helpers for the notification modal."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.widgets import Static

from sase.notifications import Notification, is_error
from sase.notification_gates.models import GateError
from sase.notification_gates.presentation import (
    GATE_ORIGIN_AGENT_ACTION_DATA_KEY,
    GATE_PANEL_ACTION_DATA_KEY,
    normalize_gate_origin_agent,
    normalize_gate_panel,
)

HITL_TAB_KEY = "hitl"
ERRORS_TAB_KEY = "errors"
MUTED_TAB_KEY = "__muted__"

_HITL_ACTIONS = frozenset(
    {
        "PlanApproval",
        "EpicApproval",
        "UserQuestion",
        "HITL",
        "LaunchApproval",
        "TaskTriage",
        "CustomGate",
    }
)
_SYNTHETIC_TAB_LABELS = {
    HITL_TAB_KEY: "HITL",
    ERRORS_TAB_KEY: "Errors",
    MUTED_TAB_KEY: "Muted",
}


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


def _notification_panel_key(notification: Notification) -> str | None:
    """Return a valid declared panel key, tolerating malformed stored data."""
    try:
        return normalize_gate_panel(
            notification.action_data.get(GATE_PANEL_ACTION_DATA_KEY)
        )
    except (AttributeError, GateError):
        return None


def notification_origin_agent(notification: Notification) -> str | None:
    """Return a valid declared origin agent, tolerating malformed stored data."""
    try:
        return normalize_gate_origin_agent(
            notification.action_data.get(GATE_ORIGIN_AGENT_ACTION_DATA_KEY)
        )
    except (AttributeError, GateError):
        return None


def _notification_modal_tab_keys(notification: Notification) -> list[str | None]:
    """Return the top-level modal tabs this notification belongs to."""
    if notification.muted:
        return [MUTED_TAB_KEY]
    panel_key = _notification_panel_key(notification)
    if panel_key is not None:
        return [panel_key]
    if notification.action in _HITL_ACTIONS:
        return [HITL_TAB_KEY]
    if is_error(notification):
        return [ERRORS_TAB_KEY]

    tags = notification_display_tags(notification)
    if tags:
        tab_keys: list[str | None] = list(tags)
        return tab_keys
    return [None]


def notification_matches_tag_tab(
    notification: Notification,
    tag: str | None,
) -> bool:
    """Return whether a notification belongs in the requested tag tab."""
    return tag in _notification_modal_tab_keys(notification)


def _notification_tab_label(tab_key: str | None) -> str:
    """Return the display label for one modal tab key."""
    if tab_key is None:
        return "General"
    synthetic_label = _SYNTHETIC_TAB_LABELS.get(tab_key)
    if synthetic_label is not None:
        return synthetic_label
    words = (word for word in re.split(r"[-_]", tab_key) if word)
    label = " ".join(word[:1].upper() + word[1:] for word in words)
    return label or tab_key


def build_notification_tag_tabs(
    notifications: list[Notification],
) -> list[NotificationTagTab]:
    """Build actionable panel tabs before informational and tag tabs."""
    counts: Counter[str | None] = Counter()
    panel_keys: set[str] = set()
    for notification in notifications:
        panel_key = _notification_panel_key(notification)
        if panel_key is not None:
            panel_keys.add(panel_key)
        for tab_key in _notification_modal_tab_keys(notification):
            counts[tab_key] += 1

    ordered_keys: list[str | None] = []

    def append_if_counted(tab_key: str | None) -> None:
        if tab_key in counts and tab_key not in ordered_keys:
            ordered_keys.append(tab_key)

    append_if_counted(HITL_TAB_KEY)
    for panel_key in sorted(
        panel_keys,
        key=lambda key: _notification_tab_label(key).casefold(),
    ):
        append_if_counted(panel_key)
    for tab_key in (ERRORS_TAB_KEY, None, "done"):
        append_if_counted(tab_key)

    ordered_keys.extend(
        sorted(
            (
                tab_key
                for tab_key in counts
                if tab_key not in ordered_keys and tab_key != MUTED_TAB_KEY
            ),
            key=lambda tab_key: _notification_tab_label(tab_key).casefold(),
        )
    )
    if MUTED_TAB_KEY in counts:
        ordered_keys.append(MUTED_TAB_KEY)

    return [
        NotificationTagTab(tab_key, _notification_tab_label(tab_key), counts[tab_key])
        for tab_key in ordered_keys
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
