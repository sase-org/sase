"""Cached per-tribe display configuration for Agents-tab panels."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from rich.cells import chop_cells

from sase.config import load_merged_config
from sase.config.core import current_config_token

from .agent_panels import PanelKey

MAX_TRIBE_ICON_CELLS = 4
MAX_TRIBE_DESCRIPTION_CHARS = 160
_TRIBE_COLOR_PATTERN = re.compile(r"#[0-9A-Fa-f]{6}")
TRIBE_IDENTITY_FALLBACK_COLOR = "#FFD75F"


@dataclass(frozen=True, slots=True)
class _TribeDisplay:
    """Resolved presentation settings for one tribe panel."""

    icon: str = ""
    color: str = ""
    initially_expanded: bool = True
    description: str = ""


DEFAULT_TRIBE_DISPLAY = _TribeDisplay()


def _sanitize_icon(raw: object) -> str:
    """Return a terminal-safe, width-bounded icon or an empty string."""
    if not isinstance(raw, str):
        return ""
    icon = raw.strip()
    if not icon or any(unicodedata.category(char) == "Cc" for char in icon):
        return ""
    chunks = chop_cells(icon, MAX_TRIBE_ICON_CELLS)
    return chunks[0].rstrip() if chunks else ""


def _sanitize_color(raw: object) -> str:
    """Return a safe RGB foreground color or an empty fallback value."""
    if not isinstance(raw, str):
        return ""
    color = raw.strip()
    return color if _TRIBE_COLOR_PATTERN.fullmatch(color) else ""


def _sanitize_description(raw: object) -> str:
    """Return a terminal-safe, length-bounded tribe description."""
    if not isinstance(raw, str):
        return ""
    collapsed = re.sub(r"\s+", " ", raw)
    text = "".join(
        char for char in collapsed if unicodedata.category(char) != "Cc"
    ).strip()
    if len(text) > MAX_TRIBE_DESCRIPTION_CHARS:
        text = text[: MAX_TRIBE_DESCRIPTION_CHARS - 1].rstrip() + "…"
    return text


@lru_cache(maxsize=1)
def _tribe_displays_for_token(
    _token: tuple[Any, ...],
) -> dict[str, _TribeDisplay]:
    """Resolve every configured tribe once per merged-config token."""
    try:
        config = load_merged_config()
    except Exception:
        return {}
    if not isinstance(config, dict):
        return {}
    ace = config.get("ace", {})
    if not isinstance(ace, dict):
        return {}
    tribes = ace.get("tribes", {})
    if not isinstance(tribes, dict):
        return {}

    displays: dict[str, _TribeDisplay] = {}
    for name, raw in tribes.items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            continue
        initially_expanded = raw.get("initially_expanded", True)
        displays[name] = _TribeDisplay(
            icon=_sanitize_icon(raw.get("icon", "")),
            color=_sanitize_color(raw.get("color", "")),
            initially_expanded=(
                initially_expanded if isinstance(initially_expanded, bool) else True
            ),
            description=_sanitize_description(raw.get("description", "")),
        )
    return displays


def _tribe_displays() -> dict[str, _TribeDisplay]:
    return _tribe_displays_for_token(current_config_token())


def _tribe_config_key(panel_key: PanelKey) -> str:
    """Return the ``ace.tribes`` config key for *panel_key*."""
    return "default" if panel_key is None else panel_key


def tribe_display_for(panel_key: PanelKey) -> _TribeDisplay:
    """Return display settings for *panel_key*, mapping no-tribe to default."""
    return _tribe_displays().get(_tribe_config_key(panel_key), DEFAULT_TRIBE_DISPLAY)


def tribe_identity_color(panel_key: PanelKey) -> str:
    """Return the effective foreground for one structured tribe identity."""
    return tribe_display_for(panel_key).color or TRIBE_IDENTITY_FALLBACK_COLOR


def tribe_identity_colors(
    panel_keys: Collection[PanelKey],
) -> dict[PanelKey, str]:
    """Resolve effective identity colors once for the distinct *panel_keys*."""
    displays = _tribe_displays()
    colors: dict[PanelKey, str] = {}
    for panel_key in panel_keys:
        display = displays.get(_tribe_config_key(panel_key), DEFAULT_TRIBE_DISPLAY)
        colors[panel_key] = display.color or TRIBE_IDENTITY_FALLBACK_COLOR
    return colors


def named_tribe_identity_colors(tribe_names: Collection[str]) -> dict[str, str]:
    """Resolve effective identity colors once for bare tribe names."""
    displays = _tribe_displays()
    return {
        tribe_name: (
            displays.get(tribe_name, DEFAULT_TRIBE_DISPLAY).color
            or TRIBE_IDENTITY_FALLBACK_COLOR
        )
        for tribe_name in tribe_names
    }


def compose_tribe_identity_style(
    color: str,
    *,
    bold: bool = False,
    dim: bool = False,
) -> str:
    """Safely compose a resolved identity foreground with Rich emphasis."""
    effective_color = _sanitize_color(color) or TRIBE_IDENTITY_FALLBACK_COLOR
    emphasis = [
        name
        for enabled, name in (
            (bold, "bold"),
            (dim, "dim"),
        )
        if enabled
    ]
    return " ".join((*emphasis, effective_color))


def tribe_identity_style(
    panel_key: PanelKey,
    *,
    bold: bool = False,
    dim: bool = False,
) -> str:
    """Return a Rich style for one structured tribe identity."""
    return compose_tribe_identity_style(
        tribe_identity_color(panel_key),
        bold=bold,
        dim=dim,
    )


def effective_collapsed_panel_keys(
    panel_keys: Collection[PanelKey] | None,
    *,
    collapsed_intent: Collection[PanelKey] = (),
    expanded_intent: Collection[PanelKey] = (),
) -> set[PanelKey]:
    """Compute effective collapsed panels without materializing config defaults."""
    collapsed = set(collapsed_intent)
    expanded = set(expanded_intent)
    if panel_keys is None:
        candidates = collapsed | expanded
        candidates.update(
            None if name == "default" else name for name in _tribe_displays()
        )
    else:
        candidates = set(panel_keys)
    return {
        key
        for key in candidates
        if key in collapsed
        or (key not in expanded and not tribe_display_for(key).initially_expanded)
    }


__all__ = [
    "DEFAULT_TRIBE_DISPLAY",
    "MAX_TRIBE_DESCRIPTION_CHARS",
    "MAX_TRIBE_ICON_CELLS",
    "TRIBE_IDENTITY_FALLBACK_COLOR",
    "compose_tribe_identity_style",
    "effective_collapsed_panel_keys",
    "named_tribe_identity_colors",
    "tribe_display_for",
    "tribe_identity_color",
    "tribe_identity_colors",
    "tribe_identity_style",
]
