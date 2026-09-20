"""Tag and panel tab helpers for the notification modal."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from rich.cells import cell_len
from rich.text import Text
from textual.events import Click, Resize
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

from .notification_modal_constants import notification_tab_shortcut

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


def modal_tag_to_core_key(tag: str | None) -> str:
    """Translate one modal tab tag into the core's tab-key vocabulary."""
    return _CORE_GENERAL_TAB_KEY if tag is None else tag


def notification_tabs_from_core(core_tabs: Any) -> list[NotificationTagTab]:
    """Return modal tab rows for an ordered list of core tab records.

    The snapshot the indicator polls already carries these tabs, so the
    indicator refresh paths translate them here rather than reclassifying.
    This is the single place tab order is finalized: a stable sort by
    effective priority descending, with the core's order as the tiebreak.
    """
    # Imported lazily: ``widgets/__init__`` is loaded from inside this
    # package's own import, so a module-scope import would cycle.
    from sase.ace.tui.widgets.notification_tab_style import (
        resolve_notification_tab_priority,
    )

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
    tabs.sort(key=lambda tab: -resolve_notification_tab_priority(tab))
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


_TagStripTier = Literal["full", "compact", "micro"]
_TAG_STRIP_SEPARATORS: dict[_TagStripTier, str] = {
    "full": " │ ",
    "compact": "│ ",
    "micro": "│",
}


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
        self._width = 0
        self._tier: _TagStripTier = "full"
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

    def on_resize(self, event: Resize) -> None:
        """Re-render so the strip reflows when its width changes."""
        width = int(event.size.width)
        if width == self._width:
            return
        self._width = width
        self.update(self._build_content())

    def _build_content(self) -> Text:
        """Build the rich tag strip content and click ranges.

        The strip clips at the modal's width, so a full-label render that
        overflows would drop whole tabs off the end — invisible and, since
        ``on_click`` only knows the ranges built here, unclickable. A fit
        ladder picks the widest representation that still fits:

        1. Full: shortcut, icon, label, count, and optional priority mark.
        2. Compact: shortcut, icon, count/mark for inactive tabs; the active
           label is retained.
        3. Micro: tightly separated shortcut/icon/count cells.

        Shortcut digits are never shed. Unknown width (not yet laid out)
        keeps the full render, matching the pre-mount default.
        """
        if self._width <= 0:
            self._tier = "full"
            return self._render_tabs("full")
        tiers: tuple[_TagStripTier, ...] = ("full", "compact", "micro")
        for tier in tiers:
            text = self._render_tabs(tier)
            if cell_len(text.plain) <= self._width or tier == "micro":
                self._tier = tier
                return text
        raise AssertionError("notification tag strip fit ladder must select a tier")

    def _render_tabs(self, tier: _TagStripTier) -> Text:
        """Render every tab at ``tier`` and record its click range.

        Click ranges are accumulated in terminal *cells* rather than in
        characters, because ``on_click`` compares them against ``event.x``. A
        single two-cell icon anywhere in the strip would otherwise shift every
        range to its right and select the wrong tab. Shortcut digits sit
        inside each tab's range so the visible number is clickable.
        """
        # Imported lazily: ``widgets/__init__`` is loaded from inside this
        # package's own import, so a module-scope import would cycle.
        from sase.ace.tui.widgets.notification_tab_style import (
            NotificationTabPriorityMark,
            notification_tab_priority_mark,
            resolve_notification_tab_color,
            resolve_notification_tab_icons,
        )

        text = Text()
        self._tab_ranges.clear()
        column = 0
        icons = resolve_notification_tab_icons(self._tabs)
        show_inactive_label = tier == "full"
        show_active_label = tier != "micro"

        def append(fragment: str, style: str) -> None:
            nonlocal column
            text.append(fragment, style=style)
            column += cell_len(fragment)

        for index, tab in enumerate(self._tabs):
            if index > 0:
                append(_TAG_STRIP_SEPARATORS[tier], "#444444")

            is_active = tab.tag == self._active_tag
            style = "bold #00D7AF" if is_active else "#888888"
            count_style = "bold #87D7FF" if is_active else "#666666"
            icon_color = resolve_notification_tab_color(tab)
            icon_style = icon_color if is_active else f"dim {icon_color}"
            start = column
            shortcut = notification_tab_shortcut(index)
            if shortcut is not None:
                digit_style = icon_color if is_active else "#666666"
                if tier == "full":
                    append(f" {shortcut} ", digit_style)
                else:
                    append(f"{shortcut} ", digit_style)
            elif tier == "full":
                append(" ", style)

            append(icons[tab.tag], icon_style)
            if (is_active and show_active_label) or (
                not is_active and show_inactive_label
            ):
                append(" ", style)
                append(shorten_notification_tag(tab.label), style)
            append(" ", style)
            append(str(tab.count), count_style)
            mark = notification_tab_priority_mark(tab)
            if isinstance(mark, NotificationTabPriorityMark):
                mark_style = mark.color if is_active else f"dim {mark.color}"
                append(mark.glyph, mark_style)
            if tier == "full":
                append(" ", style)
            self._tab_ranges[tab.tag] = (start, column)

        return text

    def on_click(self, event: Click) -> None:
        """Switch to a clicked tag tab."""
        for tag, (start, end) in self._tab_ranges.items():
            if start <= event.x < end:
                if tag != self._active_tag:
                    self.post_message(self.TabClicked(tag))
                return
