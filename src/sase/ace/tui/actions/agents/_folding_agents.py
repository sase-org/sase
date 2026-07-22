"""Compatibility facade for Agents-tab tree and grouping folding."""

from __future__ import annotations

from ._folding_agent_groups import AgentGroupFoldingMixin


class AgentTreeFoldingMixin(AgentGroupFoldingMixin):
    """Manage agent-tree and grouping-banner fold state."""


__all__ = ["AgentTreeFoldingMixin"]
