"""Lightweight shared selectors for Footprint views and reports."""

from __future__ import annotations

LENSES: tuple[str, ...] = (
    "map",
    "cold",
    "fading",
    "agent-only",
    "dead-paths",
    "friction",
    "hot",
    "coverage",
    "decisions",
)

ACTOR_SCOPES: tuple[str, ...] = ("you", "agents", "automation", "everyone")

FORMATS: tuple[str, ...] = ("rich", "json", "markdown")

KEEP_REASONS: tuple[str, ...] = (
    "rare_by_design",
    "safety",
    "agent_facing",
    "api_contract",
    "other",
)

DECISIONS: tuple[str, ...] = ("keep", "later", "cut", "clear")

__all__ = ["ACTOR_SCOPES", "DECISIONS", "FORMATS", "KEEP_REASONS", "LENSES"]
