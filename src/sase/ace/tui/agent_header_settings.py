"""Typed reader for the ``ace.agent_header`` configuration block."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_COLLAPSED_MAX_SHARE = 0.35
MAX_COLLAPSED_MAX_SHARE = 0.6
DEFAULT_COLLAPSED_PREVIEW_MAX_ROWS = 3


@dataclass(frozen=True, slots=True)
class AgentHeaderSettings:
    """Cached agent-header behavior settings used by ACE."""

    collapsed_max_share: float = DEFAULT_COLLAPSED_MAX_SHARE
    collapsed_preview_max_rows: int = DEFAULT_COLLAPSED_PREVIEW_MAX_ROWS


DEFAULT_AGENT_HEADER_SETTINGS = AgentHeaderSettings()


def parse_agent_header_settings(ace_cfg: object) -> AgentHeaderSettings:
    """Parse ``ace.agent_header`` with safe package fallbacks.

    Non-mapping ``ace`` blocks, missing or non-mapping ``agent_header``
    objects, boolean values, non-numbers, negatives and values above the
    maximum share all fall back to the default. Ints coerce to float.
    ``collapsed_preview_max_rows`` accepts a non-bool ``int >= 1`` or an
    integral ``float >= 1`` coerced to ``int``; anything else falls back to
    its default. Each key falls back on its own.
    """
    if not isinstance(ace_cfg, dict):
        return DEFAULT_AGENT_HEADER_SETTINGS
    raw = ace_cfg.get("agent_header")
    if not isinstance(raw, dict):
        return DEFAULT_AGENT_HEADER_SETTINGS
    return AgentHeaderSettings(
        collapsed_max_share=_coerce_share(raw.get("collapsed_max_share")),
        collapsed_preview_max_rows=_coerce_rows(raw.get("collapsed_preview_max_rows")),
    )


def _coerce_share(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_COLLAPSED_MAX_SHARE
    # Written so NaN also falls through to the default.
    if not 0 <= value <= MAX_COLLAPSED_MAX_SHARE:
        return DEFAULT_COLLAPSED_MAX_SHARE
    return float(value)


def _coerce_rows(value: object) -> int:
    """Coerce ``collapsed_preview_max_rows`` with a safe fallback."""
    if isinstance(value, bool):
        return DEFAULT_COLLAPSED_PREVIEW_MAX_ROWS
    if isinstance(value, int):
        if value >= 1:
            return value
        return DEFAULT_COLLAPSED_PREVIEW_MAX_ROWS
    if isinstance(value, float):
        # NaN and inf are not integers, so both fall through to the default.
        if value.is_integer() and value >= 1:
            return int(value)
        return DEFAULT_COLLAPSED_PREVIEW_MAX_ROWS
    return DEFAULT_COLLAPSED_PREVIEW_MAX_ROWS


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
    "DEFAULT_COLLAPSED_PREVIEW_MAX_ROWS",
    "MAX_COLLAPSED_MAX_SHARE",
    "AgentHeaderSettings",
    "agent_header_settings_for",
    "parse_agent_header_settings",
]
