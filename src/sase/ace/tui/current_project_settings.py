"""Typed reader for the ``ace.current_project`` configuration block."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CurrentProjectSettings:
    """Cached ``ace.current_project`` settings used by ACE.

    ``seed_agents_query`` stays off by default because the Agents-tab search
    query also feeds unread jumps and prospective clans, not just the list.
    """

    indicator: bool = True
    seed_filters: bool = True
    seed_agents_query: bool = False


def parse_current_project_settings(ace_cfg: object) -> CurrentProjectSettings:
    """Parse ``ace.current_project`` with safe package fallbacks.

    Non-mapping ``ace`` blocks, a missing or non-mapping ``current_project``
    object, and non-boolean field values all fall back to the package defaults.
    """
    if not isinstance(ace_cfg, dict):
        return CurrentProjectSettings()
    raw = ace_cfg.get("current_project")
    if not isinstance(raw, dict):
        return CurrentProjectSettings()
    return CurrentProjectSettings(
        indicator=_coerce_bool(raw.get("indicator"), default=True),
        seed_filters=_coerce_bool(raw.get("seed_filters"), default=True),
        seed_agents_query=_coerce_bool(raw.get("seed_agents_query"), default=False),
    )


def _coerce_bool(value: object, *, default: bool) -> bool:
    return value if isinstance(value, bool) else default


__all__ = [
    "CurrentProjectSettings",
    "parse_current_project_settings",
]
