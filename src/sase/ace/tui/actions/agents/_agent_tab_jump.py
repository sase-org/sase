"""Switch-then-reveal helper for cross-tab agent jumps (cross-tab-nav).

:func:`ensure_agent_tab_for_identity` switches to the tab holding a target
identity before the caller reveals it, and returns the previous key so a
failed reveal can restore it.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from sase.core.agent_tab import AgentTabKey

from ...models.agent_tab_index import ALL_AGENT_TABS
from ._tab_scope import current_agent_tab_scope

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

type AgentIdentity = tuple["AgentType", str, str | None]


def _identity_of(target: Agent | AgentIdentity) -> AgentIdentity | None:
    """Return the identity for a row or an identity tuple."""
    identity = getattr(target, "identity", None)
    if identity is not None:
        return identity
    if isinstance(target, tuple) and len(target) == 3:
        return target  # type: ignore[return-value]
    return None


def _complete_roster(owner: Any) -> list[Agent]:
    """Return the tab-independent loaded roster for jump resolution."""
    return list(
        getattr(owner, "_agents_with_children", None)
        or getattr(owner, "_agents", None)
        or ()
    )


def ensure_agent_tab_for_identity(
    owner: Any,
    target: Agent | AgentIdentity,
) -> AgentTabKey | None:
    """Switch to the tab holding *target*; return the previous key or None.

    Returns None (no switch) when the flag is off, the scope is
    ``ALL_AGENT_TABS``, the tab index is missing, the target is not loaded,
    the target already sits on the active tab, or the owner cannot switch.
    Otherwise switches via ``_switch_agents_tab(key, reason="jump")`` and
    returns the previous active key so the caller can restore it when its
    reveal fails.
    """
    if current_agent_tab_scope(owner) is ALL_AGENT_TABS:
        return None
    identity = _identity_of(target)
    if identity is None:
        return None
    index = getattr(owner, "_agent_tab_index", None)
    if index is None:
        return None
    row = next(
        (
            agent
            for agent in _complete_roster(owner)
            if getattr(agent, "identity", None) == identity
        ),
        None,
    )
    if row is None:
        return None
    try:
        key = index.key_for(row)
    except Exception:
        return None
    active = getattr(owner, "_active_agent_tab", None)
    if not isinstance(active, AgentTabKey) or key == active:
        return None
    switch = getattr(owner, "_switch_agents_tab", None)
    if not callable(switch):
        return None
    try:
        switched = switch(key, reason="jump")
    except Exception:
        return None
    return active if switched else None


def restore_agent_tab(owner: Any, previous: AgentTabKey | None) -> None:
    """Switch back to *previous* after a failed cross-tab reveal, if any."""
    if previous is None:
        return
    switch = getattr(owner, "_switch_agents_tab", None)
    if not callable(switch):
        return
    try:
        switch(previous, reason="jump-restore")
    except Exception:
        pass


def off_tab_labels_for_owner(owner: Any) -> dict[AgentIdentity, str]:
    """Map each query-result identity off the active tab to its tab label.

    Empty without an index or at the ``ALL_AGENT_TABS``
    scope. The Node Finder uses it to keep off-tab rows reachable with an
    off-tab chip instead of dropping them as not-rendered.
    """
    if current_agent_tab_scope(owner) is ALL_AGENT_TABS:
        return {}
    index = getattr(owner, "_agent_tab_index", None)
    if index is None:
        return {}
    active = getattr(owner, "_active_agent_tab", None)
    query_result = getattr(owner, "_agents_query_result", None)
    if query_result is None:
        query_result = _complete_roster(owner)
    catalog_labels = {
        entry.key: entry.label for entry in getattr(index, "catalog", ()) or ()
    }
    labels: dict[AgentIdentity, str] = {}
    for row in query_result:
        identity = getattr(row, "identity", None)
        if identity is None or identity in labels:
            continue
        try:
            key = index.key_for(row)
        except Exception:
            continue
        if key == active:
            continue
        label = catalog_labels.get(key)
        if not isinstance(label, str) or not label:
            label = key.value if key.kind == "named" else "main"
        labels[identity] = label
    return labels


class AgentTabJumpMixin:
    """Owner method for switch-then-reveal cross-tab jumps."""

    def _ensure_agent_tab_for(self, target: Agent | AgentIdentity) -> bool:
        """Switch to *target*'s tab; True when the scope changed.

        A failed reveal should restore the previous tab via
        :func:`restore_agent_tab`; use :func:`ensure_agent_tab_for_identity`
        directly when the previous key is needed.
        """
        return ensure_agent_tab_for_identity(self, target) is not None


__all__ = [
    "AgentIdentity",
    "AgentTabJumpMixin",
    "ensure_agent_tab_for_identity",
    "off_tab_labels_for_owner",
    "restore_agent_tab",
]
