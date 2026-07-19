"""Cached per-tribe display configuration for Agents-tab panels."""

from __future__ import annotations

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


@dataclass(frozen=True, slots=True)
class _TribeDisplay:
    """Resolved presentation settings for one tribe panel."""

    icon: str = ""
    initially_expanded: bool = True


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
            initially_expanded=(
                initially_expanded if isinstance(initially_expanded, bool) else True
            ),
        )
    return displays


def _tribe_displays() -> dict[str, _TribeDisplay]:
    return _tribe_displays_for_token(current_config_token())


def tribe_display_for(panel_key: PanelKey) -> _TribeDisplay:
    """Return display settings for *panel_key*, mapping no-tribe to default."""
    config_key = "default" if panel_key is None else panel_key
    return _tribe_displays().get(config_key, DEFAULT_TRIBE_DISPLAY)


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
    "MAX_TRIBE_ICON_CELLS",
    "effective_collapsed_panel_keys",
    "tribe_display_for",
]
