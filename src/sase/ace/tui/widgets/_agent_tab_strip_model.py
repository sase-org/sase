"""Agent tab strip model: descriptors, accents, tiers, and empty states.

Pure render model behind the clickable
:class:`sase.ace.tui.widgets.agent_tab_strip.AgentTabStrip` widget.
Only public names cross module boundaries here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from sase.core.agent_tab import AgentTabKey
from sase.palette_hash import hash_palette_index
from sase.project_accents import PROJECT_ACCENTS, project_accent

MACHINE_GLYPH = "\u2328"
ARRIVAL_DOT = "\u2022"
ACTIVE_PILL_LEFT = "\u2590"
ACTIVE_PILL_RIGHT = "\u258c"
KIND_DIVIDER = "\u250a"
TAB_SEPARATOR = " \u2502 "
OVERFLOW_PREV_ID = "__overflow_prev__"
OVERFLOW_NEXT_ID = "__overflow_next__"

MACHINE_GLYPH_STYLE = "#5FD7FF"
MAIN_LABEL_STYLE = "#AFAFAF"
NEUTRAL_COUNT_STYLE = "#AFAFAF"
SEPARATOR_STYLE = "#444444"
ACTIVE_TEXT_STYLE = "bold #1C1C1C"
STALE_LABEL_STYLE = "bold #FFAF00"
INVALID_LABEL_STYLE = "bold #FF5F5F"
ATTENTION_STYLES = {
    "stopped": "bold #FFAF00",
    "failed": "bold #FF5F5F",
    "unread": "bold #1a1a1a on #FFD700",
}

AgentTabStripTier = Literal["full", "compact", "micro"]
AgentTabHealth = Literal["ok", "stale", "invalid", "offline"]
AgentTabEmptyKind = Literal["empty", "query_hides", "feed_unavailable"]


@dataclass(frozen=True, slots=True)
class AgentTabDescriptor:
    """Immutable render model for one agent tab chip."""

    key: AgentTabKey
    label: str
    glyph: str = ""
    accent: str = MAIN_LABEL_STYLE
    count: int = 0
    incomplete: bool = False
    stopped: int = 0
    failed: int = 0
    unread: int = 0
    health: AgentTabHealth = "ok"
    has_arrival: bool = False
    description: str = ""
    jump_hint: str | None = None
    machine_alias: str = ""
    is_default: bool = False


def agent_tab_accent_for_name(
    name: str,
    *,
    config_color: str = "",
    enabled_projects: tuple[str, ...] = (),
) -> str:
    """Return the accent for named tab *name*.

    Configured ``ace.agent_tabs.tabs.<name>.color`` wins. An enabled
    project key reuses ``project_accent`` so ``sase`` matches ``+sase``.
    Anything else hashes into the established project palette.
    """
    cleaned = (config_color or "").strip()
    if cleaned:
        return cleaned
    lowered = name.casefold()
    for project_key in enabled_projects:
        if project_key.casefold() == lowered:
            return project_accent(project_key, among=enabled_projects)
    return PROJECT_ACCENTS[hash_palette_index(name, len(PROJECT_ACCENTS))]


def agent_tab_chip_for_key(
    key: AgentTabKey,
    *,
    colors: Mapping[str, str] | None = None,
    enabled_projects: tuple[str, ...] = (),
) -> tuple[str, str] | None:
    """Return the ``(name, style)`` row/roster chip for a named tab key.

    Returns None for default, machine, and unresolved keys: only rows on
    named tabs get a tab chip. The style is the tab's accent, bold.
    """
    if getattr(key, "kind", None) != "named":
        return None
    name = getattr(key, "value", "") or ""
    if not name:
        return None
    accent = ""
    if isinstance(colors, Mapping):
        accent = colors.get(name) or ""
    if not accent:
        accent = agent_tab_accent_for_name(name, enabled_projects=enabled_projects)
    return (name, f"bold {accent}")


def agent_tab_label_style(descriptor: AgentTabDescriptor) -> str:
    """Return the label style for *descriptor* honoring machine health."""
    if descriptor.is_default:
        return MAIN_LABEL_STYLE
    if descriptor.glyph == MACHINE_GLYPH:
        if descriptor.health in ("invalid", "offline"):
            return INVALID_LABEL_STYLE
        if descriptor.health == "stale":
            return STALE_LABEL_STYLE
        return descriptor.accent or MACHINE_GLYPH_STYLE
    return descriptor.accent or MAIN_LABEL_STYLE


@dataclass(frozen=True, slots=True)
class AgentTabEmptyState:
    """One of the three visible empty causes for the active tab."""

    kind: AgentTabEmptyKind
    title: str
    detail: str = ""


def agent_tab_empty_state(
    *,
    scoped_count: int,
    tab_has_roots: bool,
    query: str = "",
    matches_elsewhere: int = 0,
    feed_unavailable: bool = False,
    tab_label: str = "this tab",
) -> AgentTabEmptyState | None:
    """Return the empty cause for the active tab, or None when not empty."""
    if scoped_count > 0:
        return None
    if feed_unavailable:
        return AgentTabEmptyState(
            kind="feed_unavailable",
            title=f"No feed for {tab_label}",
            detail="The feed is unavailable \u2014 open Admin Center \u2192 Machines.",
        )
    if (query or "").strip() and (tab_has_roots or matches_elsewhere > 0):
        detail = f"The query hides them ({matches_elsewhere} matches elsewhere)"
        if (query or "").strip():
            detail += " \u2014 clear the filter to see this tab."
        return AgentTabEmptyState(
            kind="query_hides",
            title=f"No visible agents on {tab_label}",
            detail=detail,
        )
    return AgentTabEmptyState(
        kind="empty",
        title=f"No agents on {tab_label}",
        detail="",
    )


__all__ = [
    "ACTIVE_PILL_LEFT",
    "ACTIVE_PILL_RIGHT",
    "ACTIVE_TEXT_STYLE",
    "ARRIVAL_DOT",
    "ATTENTION_STYLES",
    "INVALID_LABEL_STYLE",
    "KIND_DIVIDER",
    "MACHINE_GLYPH",
    "MACHINE_GLYPH_STYLE",
    "MAIN_LABEL_STYLE",
    "NEUTRAL_COUNT_STYLE",
    "OVERFLOW_NEXT_ID",
    "OVERFLOW_PREV_ID",
    "SEPARATOR_STYLE",
    "STALE_LABEL_STYLE",
    "TAB_SEPARATOR",
    "AgentTabDescriptor",
    "AgentTabEmptyKind",
    "AgentTabEmptyState",
    "AgentTabHealth",
    "AgentTabStripTier",
    "agent_tab_accent_for_name",
    "agent_tab_chip_for_key",
    "agent_tab_empty_state",
    "agent_tab_label_style",
]
