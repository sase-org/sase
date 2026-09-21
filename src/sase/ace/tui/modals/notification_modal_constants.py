"""Shared constants for the notification modal."""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len


# Action badge mapping
ACTION_BADGES: dict[str | None, str] = {
    "JumpToPatch": "[CS]",
    "JumpToMentorReview": "[mentor]",
    "Tmux": "[tmux]",
    "HITL": "[HITL]",
    "LaunchApproval": "[launch]",
    "TaskTriage": "[task]",
    "BeadSnooze": "[snooze]",
    "PlanApproval": "[plan]",
    "EpicApproval": "[epic]",
    "UserQuestion": "[question]",
    "CustomGate": "[custom]",
    "GateExecutionFailed": "[gate failed]",
    "ViewErrorReport": "[error]",
    "ViewReport": "[report]",
    "OpenLaunchControl": "[models]",
}

# Gate actions intentionally have explicit defaults. A notification-provided
# icon always wins, while non-gate actions use the same table for a coherent
# inbox rather than falling back to text-only rows.
ACTION_ICONS: dict[str | None, str] = {
    None: "🔔",
    "JumpToAgent": "🤖",
    "JumpToPatch": "📋",
    "JumpToMentorReview": "👀",
    "Tmux": "🖥️",
    "HITL": "✋",
    "LaunchApproval": "🚀",
    "TaskTriage": "✦",
    "BeadSnooze": "◈",
    "PlanApproval": "📝",
    "EpicApproval": "🗺️",
    "UserQuestion": "❓",
    "CustomGate": "✨",
    "GateExecutionFailed": "!",
    "ViewErrorReport": "🚨",
    "ViewReport": "📊",
    "OpenLaunchControl": "🎛️",
}


def notification_icon(action: str | None, icon: str | None) -> str:
    """Return a notification's authored icon or its per-action default."""
    return icon or ACTION_ICONS.get(action, ACTION_ICONS[None])


HEADER_ID_PREFIX = "hdr:"

# Positional tab shortcuts in display order: 1–9, then 0 for the tenth.
# Tabs after the tenth stay unnumbered. Bindings and the tag strip both
# consume this sequence so the rendered digits cannot drift from the keys.
NOTIFICATION_TAB_SHORTCUTS: tuple[str, ...] = (
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "0",
)
NOTIFICATION_TAB_HINT_TEXT = "1-0/[]: tab"


def notification_tab_shortcut(index: int) -> str | None:
    """Return the positional shortcut for tab ``index``, or ``None`` past the tenth."""
    if 0 <= index < len(NOTIFICATION_TAB_SHORTCUTS):
        return NOTIFICATION_TAB_SHORTCUTS[index]
    return None


# The footer hint line is a single-row centered label, so it cannot wrap or
# reflow: anything wider than the modal's content width is clipped. Each hint
# variant is therefore modeled as an ordered list of fragments with a
# priority, and the footer renders the widest tier that fits the measured
# width. ``q: close`` and ``+: +1`` carry the highest priorities and survive
# every tier; low-frequency file-navigation entries shed first.
@dataclass(frozen=True)
class _NotificationHintFragment:
    """One ``key: label`` footer fragment with its shed priority."""

    key: str
    label: str
    priority: int

    @property
    def text(self) -> str:
        """Return the rendered ``key: label`` fragment."""
        return f"{self.key}: {self.label}"


# Priority ladder shared by every variant: file navigation sheds first,
# per-row state actions next, and navigation aids survive the longest after
# the always-kept close and +1 entries.
_HINT_PRIORITY_FILE_NAV = 10
_HINT_PRIORITY_ROW_STATE = 30
_HINT_PRIORITY_SCROLL = 50
_HINT_PRIORITY_TOP_BOT = 55
_HINT_PRIORITY_READ_TAB = 60
_HINT_PRIORITY_TAG_TABS = 65
_HINT_PRIORITY_SECTIONS = 70
_HINT_PRIORITY_ENTER = 80
_HINT_PRIORITY_PLUS_ONE = 90
_HINT_PRIORITY_CLOSE = 100

DEFAULT_HINT_FRAGMENTS: tuple[_NotificationHintFragment, ...] = (
    _NotificationHintFragment("Enter", "select", _HINT_PRIORITY_ENTER),
    _NotificationHintFragment("d", "debug", _HINT_PRIORITY_ROW_STATE),
    _NotificationHintFragment("m", "mark", _HINT_PRIORITY_ROW_STATE),
    _NotificationHintFragment("x", "dismiss", _HINT_PRIORITY_ROW_STATE),
    _NotificationHintFragment("M", "mute", _HINT_PRIORITY_ROW_STATE),
    _NotificationHintFragment("s", "snooze", _HINT_PRIORITY_ROW_STATE),
    _NotificationHintFragment("e", "edit", _HINT_PRIORITY_FILE_NAV),
    _NotificationHintFragment("V", "view", _HINT_PRIORITY_FILE_NAV),
    _NotificationHintFragment("Y", "copy path", _HINT_PRIORITY_FILE_NAV),
    _NotificationHintFragment("C-n/C-p", "next/prev file", _HINT_PRIORITY_FILE_NAV),
    _NotificationHintFragment("C-d/C-u", "scroll", _HINT_PRIORITY_SCROLL),
    _NotificationHintFragment("g/G", "top/bot", _HINT_PRIORITY_TOP_BOT),
    _NotificationHintFragment("R", "read tab", _HINT_PRIORITY_READ_TAB),
    _NotificationHintFragment("S", "sections", _HINT_PRIORITY_SECTIONS),
    _NotificationHintFragment("1-0/[]", "tab", _HINT_PRIORITY_TAG_TABS),
    _NotificationHintFragment("+", "+1", _HINT_PRIORITY_PLUS_ONE),
    _NotificationHintFragment("q", "close", _HINT_PRIORITY_CLOSE),
)
QUESTION_HINT_FRAGMENTS: tuple[_NotificationHintFragment, ...] = (
    _NotificationHintFragment("Enter", "answer", _HINT_PRIORITY_ENTER),
    _NotificationHintFragment("d", "debug", _HINT_PRIORITY_ROW_STATE),
    _NotificationHintFragment("C-d/C-u", "scroll", _HINT_PRIORITY_SCROLL),
    _NotificationHintFragment("g/G", "top/bot", _HINT_PRIORITY_TOP_BOT),
    _NotificationHintFragment("m", "mark", _HINT_PRIORITY_ROW_STATE),
    _NotificationHintFragment("x", "dismiss", _HINT_PRIORITY_ROW_STATE),
    _NotificationHintFragment("M", "mute", _HINT_PRIORITY_ROW_STATE),
    _NotificationHintFragment("s", "snooze", _HINT_PRIORITY_ROW_STATE),
    _NotificationHintFragment("S", "sections", _HINT_PRIORITY_SECTIONS),
    _NotificationHintFragment("1-0/[]", "tab", _HINT_PRIORITY_TAG_TABS),
    _NotificationHintFragment("+", "+1", _HINT_PRIORITY_PLUS_ONE),
    _NotificationHintFragment("q", "close", _HINT_PRIORITY_CLOSE),
)
GATE_HINT_FRAGMENTS: tuple[_NotificationHintFragment, ...] = (
    _NotificationHintFragment("Enter", "review", _HINT_PRIORITY_ENTER),
    _NotificationHintFragment("d", "debug", _HINT_PRIORITY_ROW_STATE),
    _NotificationHintFragment("C-n/C-p", "file", _HINT_PRIORITY_FILE_NAV),
    _NotificationHintFragment("C-d/C-u", "scroll", _HINT_PRIORITY_SCROLL),
    _NotificationHintFragment("g/G", "top/bot", _HINT_PRIORITY_TOP_BOT),
    _NotificationHintFragment("m", "mark", _HINT_PRIORITY_ROW_STATE),
    _NotificationHintFragment("x", "dismiss", _HINT_PRIORITY_ROW_STATE),
    _NotificationHintFragment("M", "mute", _HINT_PRIORITY_ROW_STATE),
    _NotificationHintFragment("s", "snooze", _HINT_PRIORITY_ROW_STATE),
    _NotificationHintFragment("S", "sections", _HINT_PRIORITY_SECTIONS),
    _NotificationHintFragment("1-0/[]", "tab", _HINT_PRIORITY_TAG_TABS),
    _NotificationHintFragment("+", "+1", _HINT_PRIORITY_PLUS_ONE),
    _NotificationHintFragment("q", "close", _HINT_PRIORITY_CLOSE),
)

_HINT_VARIANT_FRAGMENTS: dict[str, tuple[_NotificationHintFragment, ...]] = {
    "default": DEFAULT_HINT_FRAGMENTS,
    "question": QUESTION_HINT_FRAGMENTS,
    "gate": GATE_HINT_FRAGMENTS,
}

_HINT_FRAGMENT_SEPARATOR = "  "


def _join_hint_fragments(
    fragments: tuple[_NotificationHintFragment, ...],
) -> str:
    """Return the rendered footer line for ``fragments`` in display order."""
    return _HINT_FRAGMENT_SEPARATOR.join(fragment.text for fragment in fragments)


DEFAULT_HINT_TEXT = _join_hint_fragments(DEFAULT_HINT_FRAGMENTS)
QUESTION_HINT_TEXT = _join_hint_fragments(QUESTION_HINT_FRAGMENTS)
GATE_HINT_TEXT = _join_hint_fragments(GATE_HINT_FRAGMENTS)

# Tier ladder: each tier keeps the fragments at or above a priority floor.
# Compact (100/87/87 cells) is the tier a 120-column modal renders: the
# container is 95% of 120 (114 cells) minus the thick border and padding.
NOTIFICATION_HINT_TIERS: tuple[str, ...] = ("full", "compact", "micro", "minimal")
_NOTIFICATION_HINT_TIER_FLOORS: dict[str, int] = {
    "full": _HINT_PRIORITY_FILE_NAV,
    "compact": _HINT_PRIORITY_SCROLL,
    "micro": _HINT_PRIORITY_TAG_TABS,
    "minimal": _HINT_PRIORITY_PLUS_ONE,
}

# Modal content width at 120 columns: 95%-wide container (114 cells) minus
# the thick border (2) and horizontal padding (4). Compact peaks at 100
# cells, so every variant fits here with headroom for border rounding.
NOTIFICATION_HINT_FALLBACK_WIDTH = 108


def _notification_hint_fragments(
    variant: str,
) -> tuple[_NotificationHintFragment, ...]:
    """Return the full fragment list for one hint ``variant``."""
    return _HINT_VARIANT_FRAGMENTS[variant]


def _notification_hint_tier(variant: str, width: int) -> str:
    """Return the widest tier of ``variant`` that fits ``width`` cells.

    An unknown (not yet laid out) width keeps the full render, matching the
    tag strip's pre-mount default; the footer re-renders on resize. The
    minimal tier always wins below every width so close and +1 stay visible.
    """
    fragments = _notification_hint_fragments(variant)
    if width <= 0:
        return "full"
    for tier in NOTIFICATION_HINT_TIERS:
        floor = _NOTIFICATION_HINT_TIER_FLOORS[tier]
        text = _join_hint_fragments(tuple(f for f in fragments if f.priority >= floor))
        if cell_len(text) <= width or tier == "minimal":
            return tier
    raise AssertionError("notification hint fit ladder must select a tier")


def notification_hint_text(variant: str, width: int) -> str:
    """Return the tier-selected footer line for ``variant`` at ``width``."""
    fragments = _notification_hint_fragments(variant)
    floor = _NOTIFICATION_HINT_TIER_FLOORS[_notification_hint_tier(variant, width)]
    return _join_hint_fragments(tuple(f for f in fragments if f.priority >= floor))
