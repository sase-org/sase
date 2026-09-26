"""Typed reader for the ``ace.agent_decks`` configuration block."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_SPREAD_MAX_SCREENS = 1.5
DEFAULT_BLOCK_SPREAD_MAX_SCREENS = 1.5


@dataclass(frozen=True, slots=True)
class AgentDecksSettings:
    """Cached agent-deck behavior settings used by ACE."""

    spread_max_screens: float = DEFAULT_SPREAD_MAX_SCREENS
    block_spread_max_screens: float = DEFAULT_BLOCK_SPREAD_MAX_SCREENS


DEFAULT_AGENT_DECKS_SETTINGS = AgentDecksSettings()


def parse_agent_decks_settings(ace_cfg: object) -> AgentDecksSettings:
    """Parse ``ace.agent_decks`` with safe package fallbacks.

    Non-mapping ``ace`` blocks, missing or non-mapping ``agent_decks``
    objects, boolean values, non-numbers and negatives all fall back to
    the default. Ints coerce to float.
    """
    if not isinstance(ace_cfg, dict):
        return DEFAULT_AGENT_DECKS_SETTINGS
    raw = ace_cfg.get("agent_decks")
    if not isinstance(raw, dict):
        return DEFAULT_AGENT_DECKS_SETTINGS
    return AgentDecksSettings(
        spread_max_screens=_coerce_screens(raw.get("spread_max_screens")),
        block_spread_max_screens=_coerce_screens(
            raw.get("block_spread_max_screens"),
            DEFAULT_BLOCK_SPREAD_MAX_SCREENS,
        ),
    )


def _coerce_screens(
    value: object, default: float = DEFAULT_SPREAD_MAX_SCREENS
) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        if value < 0:
            return default
        return float(value)
    if isinstance(value, float):
        if value < 0:
            return default
        return value
    return default


def agent_decks_settings_for(widget: object) -> AgentDecksSettings:
    """Return the app's agent-decks settings, failing open to the default."""
    try:
        app = getattr(widget, "app", None)
        settings = getattr(app, "_agent_decks_settings", None)
        if isinstance(settings, AgentDecksSettings):
            return settings
    except Exception:
        pass
    return DEFAULT_AGENT_DECKS_SETTINGS


__all__ = [
    "DEFAULT_AGENT_DECKS_SETTINGS",
    "DEFAULT_BLOCK_SPREAD_MAX_SCREENS",
    "DEFAULT_SPREAD_MAX_SCREENS",
    "AgentDecksSettings",
    "agent_decks_settings_for",
    "parse_agent_decks_settings",
]
