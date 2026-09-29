"""Synchronous tab switching with per-tab memory and the minimal strip.

``_switch_agents_tab`` synchronously re-scopes the cached query result
with per-tab selection memory, and the strip refreshes on every switch.

This module is a facade preserving the original public import path. The
per-tab memory mixin lives in :mod:`_agent_tabs_switch_memory`, the
strip mixin in :mod:`_agent_tabs_switch_strip`, and the synchronous
switch core in :mod:`_agent_tabs_switch_core`.
"""

from __future__ import annotations

from ._agent_tabs_switch_core import AgentTabsSwitchCoreMixin
from ._agent_tabs_switch_memory import AgentTabsSwitchMemoryMixin
from ._agent_tabs_switch_strip import AgentTabsSwitchStripMixin


class AgentTabsSwitchMixin(
    AgentTabsSwitchMemoryMixin,
    AgentTabsSwitchStripMixin,
    AgentTabsSwitchCoreMixin,
):
    """Synchronous tab switching with per-tab memory and the strip."""


__all__ = [
    "AgentTabsSwitchMixin",
]
