"""Compatibility facade for Agents-tab tree and grouping folding."""

from __future__ import annotations

from ._folding_panel_sweep import AgentPanelFoldSweepMixin


class AgentTreeFoldingMixin(AgentPanelFoldSweepMixin):
    """Manage agent-tree and grouping-banner fold state."""


__all__ = ["AgentTreeFoldingMixin"]
