"""Stable per-tab colors, icons, labels, grouping, and priorities.

Every notification-panel tab renders with a color, so a brand-new tag tab is
never colorless. The precedence, highest first, is the user's
``ace.notification_tabs`` override, the sender-declared color carried on the
snapshot tab, a built-in default for a known key, and finally a hashed
auto-palette entry that keeps the same tag the same color across restarts.

Icons resolve through the same shape with one deliberate difference: their last
rung is a default keyed by the core's own tab *kind*, then a generic mark, never
a hash. An arbitrary color is still a usable identifier, but an arbitrary glyph
would teach the reader something false, so icons are only ever meaningful or
honestly generic.

Grouping is parsed beside the visual fields so notification-panel render paths
pay one token-cached config read. Priority is another sibling of color and icon:
every tab has a default from a ladder that restates the core's
``ordered_tab_keys`` as numbers, and an effective value that is the configured
override when one is set. Tabs sort by effective priority descending; a tab
whose effective value differs from its default renders a one-cell up or down
mark.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import Enum
from functools import lru_cache
from typing import Any, NamedTuple

from rich.cells import cell_len

from sase.ace.tui.modals.notification_modal_tags import (
    MUTED_TAB_KEY,
    NotificationTagTab,
    SNOOZED_TAB_KEY,
    shorten_notification_tag,
)
from sase.bead_type_presentation import BEAD_TYPE_VALUES, bead_type_presentation
from sase.config import load_merged_config
from sase.config.core import current_config_token
from sase.notification_gates.model_validation import GateError, validate_icon
from sase.task_type_presentation import task_type_presentation
from sase.task_types.registry import get_task_type_registry

# The core's catch-all tab key; the modal spells the same tab ``None``.
GENERAL_TAB_KEY = "general"

DEFAULT_NOTIFICATION_INDICATOR_MAX_COUNTS = 4

_COLOR_PATTERN = re.compile(r"#[0-9A-Fa-f]{6}")
_GROUPING_PATTERN = re.compile(r"[a-z][a-z0-9_]*")

# Built-in colors for the tabs ACE ships knowing about. These mirror the
# ``ace.notification_tabs`` defaults in ``default_config.yml``; the config read
# normally wins, and these keep the indicator styled if that block is emptied.
_BUILTIN_TAB_COLORS = {
    "hitl": "#FF8700",
    "errors": "#FF5F5F",
    "beads": "#AF87FF",
    GENERAL_TAB_KEY: "#FFD700",
    "snoozed": "#6C6C6C",
    "muted": "#5FAFAF",
}

# Built-in icons for the tabs ACE ships knowing about, mirroring the
# ``ace.notification_tabs`` defaults in ``default_config.yml`` exactly as the
# colors above do. Every glyph is single-cell so the top bar stays dense.
_BUILTIN_TAB_ICONS = {
    "hitl": "⚑",
    "errors": "✖",
    "beads": "◈",
    GENERAL_TAB_KEY: "✉",
    "snoozed": "☾",
    "muted": "⊘",
}

# Icons keyed by the core's own tab kind for tabs ACE has never heard of.
# Known ACE tabs use the built-in key rung above instead.
_KIND_TAB_ICONS = {
    "panel": "◆",
    "tag": "#",
}

# Reachable only for a tab that arrives with no kind at all.
_LAST_RESORT_TAB_ICON = "•"

# Default sort weights restating the core's ``ordered_tab_keys`` as numbers.
# Key rungs beat kind rungs so a literal ``__muted__`` tag still sits last.
_KEY_TAB_PRIORITIES = {SNOOZED_TAB_KEY: -10, MUTED_TAB_KEY: -20}
_KIND_TAB_PRIORITIES = {
    "hitl": 60,
    "panel": 50,
    "errors": 40,
    "general": 30,
    "tag": 10,
}
_DONE_TAB_PRIORITY = 20
_UNKNOWN_KIND_TAB_PRIORITY = 10

MIN_NOTIFICATION_TAB_PRIORITY = -1000
MAX_NOTIFICATION_TAB_PRIORITY = 1000

# A configured or declared icon wider than this would blow out the top bar.
_MAX_TAB_ICON_CELLS = 2

# Six 256-color-safe hexes for tabs nobody has named, chosen to stay legible on
# the ACE top bar and to read as distinct from every built-in default above.
_AUTO_PALETTE = (
    "#5FD7AF",
    "#87AFFF",
    "#D7AF5F",
    "#FF87D7",
    "#87D75F",
    "#AFAFD7",
)


class NotificationTabPriorityMark(NamedTuple):
    """One-cell mark shown when a tab's priority differs from its default."""

    glyph: str
    color: str


_RAISED_PRIORITY_MARK = NotificationTabPriorityMark(glyph="▴", color="#FFAF00")
_LOWERED_PRIORITY_MARK = NotificationTabPriorityMark(glyph="▾", color="#8A8A8A")


class _ConfiguredTabStyle(NamedTuple):
    """One tab's user-configured styling, empty where nothing was configured."""

    color: str
    icon: str
    priority: int | None = None
    grouping: str = ""


_EMPTY_TAB_STYLE = _ConfiguredTabStyle(color="", icon="", priority=None, grouping="")


class _IconRung(Enum):
    CONFIGURED = "configured"
    DECLARED = "declared"
    BEAD_TYPE = "bead_type"
    TASK_TYPE = "task_type"
    BUILTIN = "builtin"
    KIND = "kind"
    LAST_RESORT = "last_resort"


_RERESOLVABLE_ICON_RUNGS = frozenset({_IconRung.KIND, _IconRung.LAST_RESORT})


def _notification_tab_key(tab: NotificationTagTab) -> str:
    """Return the core tab key for *tab*, spelling the general tab out."""
    return GENERAL_TAB_KEY if tab.tag is None else tab.tag


def _notification_tab_config_key(tab: NotificationTagTab) -> str:
    """Return the ``ace.notification_tabs`` key users write for *tab*.

    Config keys use the user-facing names, so the internal ``__snoozed__`` and
    ``__muted__`` keys are not something anyone has to type.
    """
    return notification_tab_config_key_for_tag(tab.tag)


def notification_tab_config_key_for_tag(tag: str | None) -> str:
    """Return the ``ace.notification_tabs`` key users write for *tag*."""
    key = GENERAL_TAB_KEY if tag is None else tag
    if key == SNOOZED_TAB_KEY:
        return "snoozed"
    if key == MUTED_TAB_KEY:
        return "muted"
    return key


def notification_tab_label(tab: NotificationTagTab) -> str:
    """Return the bounded label the indicator tooltip renders for *tab*."""
    return shorten_notification_tag(tab.label)


def default_notification_tab_priority(tab: NotificationTagTab) -> int:
    """Return the ladder default for *tab*, independent of any config override.

    Resolution is key first (so a literal ``__muted__`` / ``__snoozed__`` tag
    still sits in the put-away slot the core pins by key), then ``done`` only
    when the kind is ``tag`` (a declared ``panel: "done"`` stays a panel), then
    kind, then the unknown-kind fallback that matches the core's remaining
    bucket.
    """
    key = _notification_tab_key(tab)
    keyed = _KEY_TAB_PRIORITIES.get(key)
    if keyed is not None:
        return keyed
    if key == "done" and tab.kind == "tag":
        return _DONE_TAB_PRIORITY
    kinded = _KIND_TAB_PRIORITIES.get(tab.kind)
    if kinded is not None:
        return kinded
    return _UNKNOWN_KIND_TAB_PRIORITY


def resolve_notification_tab_priority(tab: NotificationTagTab) -> int:
    """Return the effective sort weight for one notification tab."""
    configured = _configured_tab_style(_notification_tab_config_key(tab)).priority
    if configured is not None:
        return configured
    return default_notification_tab_priority(tab)


def resolve_notification_tab_grouping(config_key: str) -> str:
    """Return the configured grouping strategy id for one tab key, if any."""
    return _configured_tab_style(config_key).grouping


def notification_tab_priority_mark(
    tab: NotificationTagTab,
) -> NotificationTabPriorityMark | None:
    """Return the one-cell deviation mark for *tab*, or ``None`` when equal."""
    effective = resolve_notification_tab_priority(tab)
    default = default_notification_tab_priority(tab)
    if effective > default:
        return _RAISED_PRIORITY_MARK
    if effective < default:
        return _LOWERED_PRIORITY_MARK
    return None


def resolve_notification_tab_color(tab: NotificationTagTab) -> str:
    """Return the effective foreground color for one notification tab."""
    config_key = _notification_tab_config_key(tab)
    configured = _configured_tab_style(config_key).color
    if configured:
        return configured
    declared = _sanitize_color(tab.color)
    if declared:
        return declared
    if config_key in BEAD_TYPE_VALUES:
        return bead_type_presentation(config_key).accent_color
    task_type = _task_type_tab_glyph_and_color(config_key)
    if task_type is not None:
        return task_type[1]
    return _default_notification_tab_color(config_key)


def resolve_notification_tab_icons(
    tabs: Sequence[NotificationTagTab],
) -> dict[str | None, str]:
    """Return collision-aware effective icons for a whole tab render.

    Icons explicitly configured by a human, declared by a sender, or built in
    for a known ACE tab are never moved. Generic kind and last-resort icons are
    re-derived from the tab key when they collide with an already claimed glyph.
    """
    resolved = [(tab, *_resolve_tab_icon(tab)) for tab in tabs]
    claimed = {
        icon for _tab, icon, rung in resolved if rung not in _RERESOLVABLE_ICON_RUNGS
    }
    icons: dict[str | None, str] = {}
    for tab, icon, rung in resolved:
        final = icon
        if rung in _RERESOLVABLE_ICON_RUNGS:
            if final in claimed:
                derived = _derive_icon_from_tab_key(_notification_tab_key(tab), claimed)
                if derived:
                    final = derived
            claimed.add(final)
        icons[tab.tag] = final
    return icons


def _resolve_tab_icon(tab: NotificationTagTab) -> tuple[str, _IconRung]:
    config_key = _notification_tab_config_key(tab)
    configured = _configured_tab_style(config_key).icon
    if configured:
        return configured, _IconRung.CONFIGURED
    declared = _sanitize_icon(tab.icon)
    if declared:
        return declared, _IconRung.DECLARED
    if config_key in BEAD_TYPE_VALUES:
        return bead_type_presentation(config_key).glyph, _IconRung.BEAD_TYPE
    task_type = _task_type_tab_glyph_and_color(config_key)
    if task_type is not None:
        return task_type[0], _IconRung.TASK_TYPE
    builtin = _BUILTIN_TAB_ICONS.get(config_key)
    if builtin is not None:
        return builtin, _IconRung.BUILTIN
    kind = _KIND_TAB_ICONS.get(tab.kind)
    if kind is not None:
        return kind, _IconRung.KIND
    return _LAST_RESORT_TAB_ICON, _IconRung.LAST_RESORT


def _task_type_tab_glyph_and_color(config_key: str) -> tuple[str, str] | None:
    """Return the resolved ``(glyph, accent_color)`` for *config_key*, if any.

    Only a slug the live registry actually knows about qualifies -- an
    arbitrary tag name must never pick up the degraded ``unknown`` styling
    ``task_type_presentation`` would otherwise hand back for every string.
    """
    if config_key not in get_task_type_registry().by_slug:
        return None
    presentation = task_type_presentation(config_key)
    return presentation.glyph, presentation.accent_color


def _derive_icon_from_tab_key(tab_key: str, claimed: set[str]) -> str:
    for character in tab_key:
        if character.isascii() and character.isalnum():
            candidate = character.lower()
            if candidate not in claimed:
                return candidate
    return ""


def _default_notification_tab_color(config_key: str) -> str:
    """Return the built-in or auto-palette color for one user-facing key."""
    builtin = _BUILTIN_TAB_COLORS.get(config_key)
    if builtin is not None:
        return builtin
    return _AUTO_PALETTE[_fnv1a32(config_key) % len(_AUTO_PALETTE)]


def notification_indicator_max_counts() -> int:
    """Return how many per-tab chips the indicator renders before ``+N``."""
    return _indicator_max_counts_for_token(current_config_token())


def _fnv1a32(value: str) -> int:
    """Hash *value* with FNV-1a so a tag keeps its color across processes."""
    digest = 0x811C9DC5
    for byte in value.encode("utf-8"):
        digest = ((digest ^ byte) * 0x01000193) & 0xFFFFFFFF
    return digest


def _sanitize_color(raw: object) -> str:
    """Return a safe RGB foreground, or an empty string for stored junk."""
    if not isinstance(raw, str):
        return ""
    color = raw.strip()
    return color if _COLOR_PATTERN.fullmatch(color) else ""


def _sanitize_icon(raw: object) -> str:
    """Return a safe single-glyph icon, or an empty string for stored junk.

    ``validate_icon`` is the one definition of a legal gate icon, so it decides
    here too; the extra cell-width guard is ACE's own, because an icon the gate
    path would happily accept can still be wide enough to skew the top bar.
    """
    try:
        icon = validate_icon(raw, "icon")
    except GateError:
        return ""
    if icon is None or cell_len(icon) > _MAX_TAB_ICON_CELLS:
        return ""
    return icon


def _sanitize_priority(raw: object) -> int | None:
    """Return a legal sort weight, or ``None`` for stored junk.

    ``bool`` is a subclass of ``int`` and must be rejected explicitly; an
    out-of-range value is unset rather than clamped, so a rejected override
    never looks like a deviation from the default.
    """
    if not isinstance(raw, int) or isinstance(raw, bool):
        return None
    if raw < MIN_NOTIFICATION_TAB_PRIORITY or raw > MAX_NOTIFICATION_TAB_PRIORITY:
        return None
    return raw


def _sanitize_grouping(raw: object) -> str:
    """Return a safe strategy id, or an empty string for stored junk."""
    if not isinstance(raw, str):
        return ""
    grouping = raw.strip()
    return grouping if _GROUPING_PATTERN.fullmatch(grouping) else ""


def _ace_config() -> dict[str, Any]:
    try:
        config = load_merged_config()
    except Exception:
        return {}
    if not isinstance(config, dict):
        return {}
    ace = config.get("ace", {})
    return ace if isinstance(ace, dict) else {}


@lru_cache(maxsize=1)
def _configured_tab_styles_for_token(
    _token: tuple[Any, ...],
) -> dict[str, _ConfiguredTabStyle]:
    """Resolve every configured tab color, icon, priority, and grouping per token.

    These fields are parsed together so a render pays one config read rather
    than one per styled attribute.
    """
    tabs = _ace_config().get("notification_tabs", {})
    if not isinstance(tabs, dict):
        return {}
    styles: dict[str, _ConfiguredTabStyle] = {}
    for name, raw in tabs.items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            continue
        style = _ConfiguredTabStyle(
            color=_sanitize_color(raw.get("color", "")),
            icon=_sanitize_icon(raw.get("icon", "")),
            priority=_sanitize_priority(raw.get("priority")),
            grouping=_sanitize_grouping(raw.get("grouping", "")),
        )
        if style != _EMPTY_TAB_STYLE:
            styles[name] = style
    return styles


@lru_cache(maxsize=1)
def _indicator_max_counts_for_token(_token: tuple[Any, ...]) -> int:
    raw = _ace_config().get(
        "notification_indicator_max_counts",
        DEFAULT_NOTIFICATION_INDICATOR_MAX_COUNTS,
    )
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
        return DEFAULT_NOTIFICATION_INDICATOR_MAX_COUNTS
    return raw


def _configured_tab_style(config_key: str) -> _ConfiguredTabStyle:
    """Return the user's configured styling for one user-facing tab key."""
    styles = _configured_tab_styles_for_token(current_config_token())
    return styles.get(config_key, _EMPTY_TAB_STYLE)


__all__ = [
    "DEFAULT_NOTIFICATION_INDICATOR_MAX_COUNTS",
    "GENERAL_TAB_KEY",
    "NotificationTabPriorityMark",
    "default_notification_tab_priority",
    "notification_indicator_max_counts",
    "notification_tab_label",
    "notification_tab_config_key_for_tag",
    "notification_tab_priority_mark",
    "resolve_notification_tab_color",
    "resolve_notification_tab_grouping",
    "resolve_notification_tab_icons",
    "resolve_notification_tab_priority",
]
