"""Stable per-tab colors and labels for the notification indicator.

Every notification-panel tab renders with a color, so a brand-new tag tab is
never colorless. The precedence, highest first, is the user's
``ace.notification_tabs`` override, the sender-declared color carried on the
snapshot tab, a built-in default for a known key, and finally a hashed
auto-palette entry that keeps the same tag the same color across restarts.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from sase.ace.tui.modals.notification_modal_tags import (
    MUTED_TAB_KEY,
    NotificationTagTab,
    SNOOZED_TAB_KEY,
    shorten_notification_tag,
)
from sase.config import load_merged_config
from sase.config.core import current_config_token

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
    configured = _configured_tab_colors().get(_notification_tab_config_key(tab))
    if configured:
        return configured
    declared = _sanitize_color(tab.color)
    if declared:
        return declared
    return _default_notification_tab_color(_notification_tab_config_key(tab))


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
def _configured_tab_colors_for_token(
    _token: tuple[Any, ...],
) -> dict[str, str]:
    """Resolve every configured tab color once per merged-config token."""
    tabs = _ace_config().get("notification_tabs", {})
    if not isinstance(tabs, dict):
        return {}
    colors: dict[str, str] = {}
    for name, raw in tabs.items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            continue
        color = _sanitize_color(raw.get("color", ""))
        if color:
            colors[name] = color
    return colors


@lru_cache(maxsize=1)
def _indicator_max_counts_for_token(_token: tuple[Any, ...]) -> int:
    raw = _ace_config().get(
        "notification_indicator_max_counts",
        DEFAULT_NOTIFICATION_INDICATOR_MAX_COUNTS,
    )
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
        return DEFAULT_NOTIFICATION_INDICATOR_MAX_COUNTS
    return raw


def _configured_tab_colors() -> dict[str, str]:
    return _configured_tab_colors_for_token(current_config_token())


__all__ = [
    "DEFAULT_NOTIFICATION_INDICATOR_MAX_COUNTS",
    "GENERAL_TAB_KEY",
    "notification_indicator_max_counts",
    "notification_tab_label",
    "resolve_notification_tab_color",
]
