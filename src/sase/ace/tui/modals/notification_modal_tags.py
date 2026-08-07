"""Tag and panel tab helpers for the notification modal."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.events import Click
from textual.message import Message
from textual.widgets import Static

from sase.core.notification_store_facade import classify_notification_tabs
from sase.notifications import Notification, is_error
from sase.notification_gates.models import GateError
from sase.notification_gates.presentation import (
    GATE_ORIGIN_AGENT_ACTION_DATA_KEY,
    GATE_PANEL_ACTION_DATA_KEY,
    normalize_gate_origin_agent,
    normalize_gate_panel,
)

# The Rust core still keys this synthetic tab "hitl" internally; only the
# Python-owned display label below has changed to "Gates".
GATES_TAB_KEY = "hitl"
ERRORS_TAB_KEY = "errors"
MUTED_TAB_KEY = "__muted__"
SNOOZED_TAB_KEY = "__snoozed__"

# The core names the catch-all tab; the modal has always spelled it ``None``.
_CORE_GENERAL_TAB_KEY = "general"

# Mirrors the core's HITL_ACTIONS list exactly; a parity test depends on that.
# BeadSnooze deliberately stays out: it declares panel: "beads" and routes
# there by the higher-precedence panel rule.
_GATE_TAB_ACTIONS = frozenset(
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
    GATES_TAB_KEY: "Gates",
    ERRORS_TAB_KEY: "Errors",
    MUTED_TAB_KEY: "Muted",
    SNOOZED_TAB_KEY: "Snoozed",
}


@dataclass(frozen=True)
class NotificationTagTab:
    """One notification tag tab in display order."""

    tag: str | None
    label: str
    count: int
    kind: str = ""
    oldest_activity_at: str | None = None
    next_wake_at: str | None = None
    color: str | None = None
    icon: str | None = None


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


def _notification_modal_tab_key(notification: Notification) -> str | None:
    """Return the one top-level modal tab that owns this notification.

    Mirrors the core's precedence so a single-row membership question needs no
    FFI call; ``classify_notification_modal_tabs`` classifies whole pages in
    Rust and a parity test keeps the two from drifting.
    """
    if notification.muted:
        if notification.snooze_until:
            return SNOOZED_TAB_KEY
        return MUTED_TAB_KEY
    panel_key = _notification_panel_key(notification)
    if panel_key is not None:
        return panel_key
    if notification.action in _GATE_TAB_ACTIONS:
        return GATES_TAB_KEY
    if is_error(notification):
        return ERRORS_TAB_KEY

    tags = notification_display_tags(notification)
    if tags:
        return tags[0]
    return None


def notification_matches_tag_tab(
    notification: Notification,
    tag: str | None,
) -> bool:
    """Return whether a notification belongs in the requested tag tab."""
    return _notification_modal_tab_key(notification) == tag


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


def _modal_tag_from_core_key(core_key: str) -> str | None:
    """Translate one core tab key into the modal's tag vocabulary."""
    return None if core_key == _CORE_GENERAL_TAB_KEY else core_key


def notification_tabs_from_core(core_tabs: Any) -> list[NotificationTagTab]:
    """Return modal tab rows for an ordered list of core tab records.

    The snapshot the indicator polls already carries these tabs, so the
    indicator refresh paths translate them here rather than reclassifying.
    """
    tabs: list[NotificationTagTab] = []
    for tab in core_tabs or []:
        tag = _modal_tag_from_core_key(tab.key)
        tabs.append(
            NotificationTagTab(
                tag=tag,
                label=_notification_tab_label(tag),
                count=tab.count,
                kind=tab.kind,
                oldest_activity_at=tab.oldest_activity_at,
                next_wake_at=tab.next_wake_at,
                color=tab.color,
                # core_tabs also carries hand-built test doubles that predate
                # this field; tolerate their absence the way tab.color once
                # needed to for an older core.
                icon=getattr(tab, "icon", None),
            )
        )
    return tabs


def classify_notification_modal_tabs(
    notifications: list[Notification],
) -> tuple[list[NotificationTagTab], dict[str, str | None]]:
    """Return the ordered tabs and each row's owning tab, in one core call."""
    classification = classify_notification_tabs(notifications)
    tabs = notification_tabs_from_core(classification.tabs)
    row_tab_keys = {
        row_id: _modal_tag_from_core_key(core_key)
        for row_id, core_key in classification.row_tab_keys.items()
    }
    return tabs, row_tab_keys


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
