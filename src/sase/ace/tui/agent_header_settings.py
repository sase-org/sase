"""Typed reader for the ``ace.agent_header`` configuration block."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_COLLAPSED_MAX_SHARE = 0.35
MAX_COLLAPSED_MAX_SHARE = 0.6


@dataclass(frozen=True, slots=True)
class AgentHeaderSettings:
    """Cached agent-header behavior settings used by ACE."""

    collapsed_max_share: float = DEFAULT_COLLAPSED_MAX_SHARE


DEFAULT_AGENT_HEADER_SETTINGS = AgentHeaderSettings()


def parse_agent_header_settings(ace_cfg: object) -> AgentHeaderSettings:
    """Parse ``ace.agent_header`` with safe package fallbacks.

    Non-mapping ``ace`` blocks, missing or non-mapping ``agent_header``
    objects, boolean values, non-numbers, negatives and values above the
    maximum share all fall back to the default. Ints coerce to float.
    """
    if not isinstance(ace_cfg, dict):
        return DEFAULT_AGENT_HEADER_SETTINGS
    raw = ace_cfg.get("agent_header")
    if not isinstance(raw, dict):
        return DEFAULT_AGENT_HEADER_SETTINGS
    return AgentHeaderSettings(
        collapsed_max_share=_coerce_share(raw.get("collapsed_max_share")),
    )


def _coerce_share(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_COLLAPSED_MAX_SHARE
    # Written so NaN also falls through to the default.
    if not 0 <= value <= MAX_COLLAPSED_MAX_SHARE:
        return DEFAULT_COLLAPSED_MAX_SHARE
    return float(value)


def agent_header_settings_for(widget: object) -> AgentHeaderSettings:
    """Return the app's agent-header settings, failing open to the default."""
    try:
        app = getattr(widget, "app", None)
        settings = getattr(app, "_agent_header_settings", None)
        if isinstance(settings, AgentHeaderSettings):
            return settings
    except Exception:
        pass
    return DEFAULT_AGENT_HEADER_SETTINGS


__all__ = [
    "DEFAULT_AGENT_HEADER_SETTINGS",
    "DEFAULT_COLLAPSED_MAX_SHARE",
    "MAX_COLLAPSED_MAX_SHARE",
    "AgentHeaderSettings",
    "agent_header_settings_for",
    "parse_agent_header_settings",
]
