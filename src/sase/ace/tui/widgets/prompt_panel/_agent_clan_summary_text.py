"""Shared clan-summary Rich-markup parsing."""

from __future__ import annotations

from rich.errors import MarkupError
from rich.text import Text

from ...models.agent import Agent


def clan_summary_text(agent: Agent) -> Text:
    """Return a clan summary parsed as Rich markup with a plain fallback."""
    raw = agent.clan_summary or ""
    try:
        return Text.from_markup(raw)
    except MarkupError:
        return Text(raw)


__all__ = ["clan_summary_text"]
