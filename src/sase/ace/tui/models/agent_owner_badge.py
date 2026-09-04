"""Owner-badge labels for imported agent provenance."""

from __future__ import annotations

from sase.core.agent_identity_facade import imported_owner_badge_label

from .agent import Agent


def agent_owner_badge_label(agent: Agent) -> str | None:
    """Return the compact owner badge for one imported agent, if any."""
    owner = agent.imported_source_owner
    if owner is None:
        return None
    return imported_owner_badge_label(owner)


__all__ = ["agent_owner_badge_label"]
