"""Shared owner-badge rendering for imported agent provenance."""

from __future__ import annotations

from rich.text import Text

from ..models.agent import Agent
from ..models.agent_owner_badge import agent_owner_badge_label
from ._agent_list_styling import _OWNER_BADGE_STYLE


def append_owner_badge(
    text: Text,
    agent: Agent,
    *,
    dim: bool = False,
) -> None:
    """Append `` [owner]`` after an identity name when provenance is known."""
    label = agent_owner_badge_label(agent)
    if not label:
        return
    color = _OWNER_BADGE_STYLE.removeprefix("bold ")
    style = f"dim {color}" if dim else _OWNER_BADGE_STYLE
    text.append(" [")
    text.append(label, style=style)
    text.append("]")


__all__ = ["append_owner_badge"]
