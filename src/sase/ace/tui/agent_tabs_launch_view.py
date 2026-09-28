"""Launch-from-view (R1) helpers for agent tabs (epic sase-1bc).

View inheritance applies to a TUI prompt-bar launch submitted while Agents
is the current main tab and a *named* tab is active. It never applies from
the default tab, a machine tab, or the All-tabs level, and it is
controlled by ``ace.agent_tabs.launch_from_view`` (default True).
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.agent_tabs_settings import launch_from_view_enabled
from sase.core.agent_tab import AgentTabKey

__all__ = [
    "active_machine_tab_alias",
    "view_inherited_tab_name",
]


def view_inherited_tab_name(app: Any) -> str | None:
    """Return the active named tab for R1 inheritance, or None.

    None covers every opt-out: ``launch_from_view`` off, a non-Agents
    main tab, and any active scope that is not a named tab (default,
    machine, unresolved, or All-tabs).
    """
    if getattr(app, "current_tab", None) != "agents":
        return None
    active = getattr(app, "_active_agent_tab", None)
    if not isinstance(active, AgentTabKey):
        return None
    if active.kind != "named" or not active.value:
        return None
    if not launch_from_view_enabled():
        return None
    return active.value


def active_machine_tab_alias(app: Any) -> str | None:
    """Return the active remote machine tab's alias, or None.

    None when the active scope is not a remote machine tab (named,
    default, unresolved, All-tabs, or the ``local`` tab).
    The alias comes from the catalog label (``"⌨ <alias>"``); the key
    only carries the installation id.
    """
    active = getattr(app, "_active_agent_tab", None)
    if not isinstance(active, AgentTabKey) or active.kind != "machine":
        return None
    from sase.ace.tui.actions.agents._agent_tabs_catalog import (
        catalog_view_for_owner,
    )

    for entry in catalog_view_for_owner(app):
        if entry.key == active:
            label = entry.label or ""
            if label.startswith("⌨ "):
                alias = label[2:].strip()
                if alias and alias != "local":
                    return alias
            return None
    return None
