"""Tab switching, persistence, keys, minimal strip, and perf (tab-state-keys).

With the ``agent_tabs`` flag off every entry point is a no-op: the scope
stays the default key, no strip appears, and ``[``/``]`` do nothing on the
Agents tab. With the flag on, :meth:`AgentTabsMixin._switch_agents_tab`
synchronously re-scopes the cached query result with per-tab selection
memory, :meth:`AgentTabsMixin._reconcile_active_agent_tab` maintains the
startup selection, the emptied-tab latch, and the machine-disappearance
fallback after every index rebuild, and the active key persists off-thread.

This module is a facade preserving the original public import path. The
catalog/strip/scope helpers live in :mod:`_agent_tabs_catalog`, the
switch/memory/strip mixin in :mod:`_agent_tabs_switch`, and the
reconcile/persistence mixin in :mod:`_agent_tabs_lifecycle`.
"""

from __future__ import annotations

from ._agent_tabs_catalog import (
    bulk_scope_label_for_owner,
    marked_off_tab_count_for_owner,
    strip_visible_for_owner,
)
from ._agent_tabs_lifecycle import AgentTabsLifecycleMixin
from ._agent_tabs_switch import AgentTabsSwitchMixin


class AgentTabsMixin(AgentTabsSwitchMixin, AgentTabsLifecycleMixin):
    """Synchronous tab switching with per-tab memory and persistence."""


__all__ = [
    "AgentTabsMixin",
    "bulk_scope_label_for_owner",
    "marked_off_tab_count_for_owner",
    "strip_visible_for_owner",
]
