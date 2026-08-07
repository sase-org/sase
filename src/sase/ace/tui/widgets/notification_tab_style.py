"""Stable per-tab colors, icons, and labels for the notification indicator.

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
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, NamedTuple

from rich.cells import cell_len

from sase.ace.tui.modals.notification_modal_tags import (
    MUTED_TAB_KEY,
    NotificationTagTab,
    SNOOZED_TAB_KEY,
    shorten_notification_tag,
)
from sase.config import load_merged_config
from sase.config.core import current_config_token
from sase.notification_gates.model_validation import GateError, validate_icon

# The core's catch-all tab key; the modal spells the same tab ``None``.
GENERAL_TAB_KEY = "general"

DEFAULT_NOTIFICATION_INDICATOR_MAX_COUNTS = 4

_COLOR_PATTERN = re.compile(r"#[0-9A-Fa-f]{6}")

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

# Icons keyed by the core's own tab kind, so a tab ACE has never heard of still
# gets a glyph that says something true about what kind of tab it is.
_KIND_TAB_ICONS = {
    "hitl": "⚑",
    "errors": "✖",
    "general": "✉",
    "snoozed": "☾",
    "muted": "⊘",
    "panel": "◆",
    "tag": "#",
}

# Reachable only for a tab that arrives with no kind at all.
_LAST_RESORT_TAB_ICON = "•"

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


class _ConfiguredTabStyle(NamedTuple):
    """One tab's user-configured styling, empty where nothing was configured."""

    color: str
    icon: str


_EMPTY_TAB_STYLE = _ConfiguredTabStyle(color="", icon="")


def _notification_tab_key(tab: NotificationTagTab) -> str:
    """Return the core tab key for *tab*, spelling the general tab out."""
    return GENERAL_TAB_KEY if tab.tag is None else tab.tag


def _notification_tab_config_key(tab: NotificationTagTab) -> str:
    """Return the ``ace.notification_tabs`` key users write for *tab*.

    Config keys use the user-facing names, so the internal ``__snoozed__`` and
    ``__muted__`` keys are not something anyone has to type.
    """
    key = _notification_tab_key(tab)
    if key == SNOOZED_TAB_KEY:
        return "snoozed"
    if key == MUTED_TAB_KEY:
        return "muted"
    return key


def notification_tab_label(tab: NotificationTagTab) -> str:
    """Return the bounded label the indicator tooltip renders for *tab*."""
    return shorten_notification_tag(tab.label)


def resolve_notification_tab_color(tab: NotificationTagTab) -> str:
    """Return the effective foreground color for one notification tab."""
    config_key = _notification_tab_config_key(tab)
    configured = _configured_tab_style(config_key).color
    if configured:
        return configured
    declared = _sanitize_color(tab.color)
    if declared:
        return declared
    return _default_notification_tab_color(config_key)


def resolve_notification_tab_icon(tab: NotificationTagTab) -> str:
    """Return the effective icon for one notification tab.

    The chain never comes up empty: configuration, then the sender-declared
    icon the core donates from the newest member row, then a built-in default
    for a key ACE knows, then a default for the tab's kind, then a generic mark.
    """
    config_key = _notification_tab_config_key(tab)
    configured = _configured_tab_style(config_key).icon
    if configured:
        return configured
    declared = _sanitize_icon(tab.icon)
    if declared:
        return declared
    builtin = _BUILTIN_TAB_ICONS.get(config_key)
    if builtin is not None:
        return builtin
    return _KIND_TAB_ICONS.get(tab.kind, _LAST_RESORT_TAB_ICON)


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
    """Resolve every configured tab color and icon per merged-config token.

    Color and icon are parsed together so a render pays one config read rather
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
    "notification_indicator_max_counts",
    "notification_tab_label",
    "resolve_notification_tab_color",
    "resolve_notification_tab_icon",
]
