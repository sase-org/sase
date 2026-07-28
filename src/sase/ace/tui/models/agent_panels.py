"""Panel-collection model for the Agents tab.

Each Agents-tab panel renders a tribe bucket of agents. Panels have a canonical
base order:

* The reserved ``@default`` panel (key ``None``) appears first only when at
  least one visible agent has no effective tribe, or when the agent list is
  empty. Explicit ``default`` assignments normalize into the same panel.
* Tribe panels are keyed by tribe, sorted alphabetically (case-insensitive).
  Their order matches the order the user used to see as tribe-level banners
  in the old three-level tree.

Split-panel rendering applies one additional stable partition to that base
order: expanded panels precede collapsed panels.  Both partitions retain the
canonical order, so panel layout is deterministic rather than depending on
collapse time or set iteration order.

Every structural descendant inherits its outer rendered root's effective tribe,
so grouping never splits a clan or agent-family subtree across panels.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from typing import cast

from sase.core.agent_tribe import RESERVED_DEFAULT_TRIBE

from .agent import Agent
from ._agent_tree import (
    presentation_anchor,
    presentation_anchor_lookup,
    tree_parent_lookup,
)

#: Canonical display identity for the reserved fallback tribe.
DEFAULT_AGENT_TRIBE = RESERVED_DEFAULT_TRIBE

#: Panel key type — ``None`` for ``@default``; a tribe string otherwise.
PanelKey = str | None


def normalize_panel_key(tribe: str | None) -> PanelKey:
    """Return the stable internal panel key for a stored/effective tribe."""
    if not tribe or tribe == DEFAULT_AGENT_TRIBE:
        return None
    return tribe


def effective_panel_tribe(panel_key: PanelKey) -> str:
    """Return the display-facing tribe identity for an internal panel key."""
    normalized = normalize_panel_key(panel_key)
    return DEFAULT_AGENT_TRIBE if normalized is None else normalized


def agent_panel_label(panel_key: PanelKey) -> str:
    """Return the canonical user-facing label for an Agents-tab panel."""
    return f"@{effective_panel_tribe(panel_key)}"


def is_reserved_default_panel(panel_key: PanelKey) -> bool:
    """Return whether *panel_key* identifies the synthesized default bucket."""
    return normalize_panel_key(panel_key) is None


@dataclass(frozen=True)
class PanelIsolationRevert:
    """Session-local panel layout remembered by the ``H`` solo toggle."""

    target_key: PanelKey
    collapsed_before: frozenset[PanelKey]


def _build_parent_lookup(agents: list[Agent]) -> dict[str, Agent]:
    return tree_parent_lookup(agents)


def _panel_key_for_agent(
    agent: Agent,
    parent_lookup: dict[str, Agent],
    anchors: dict[int, Agent],
) -> PanelKey:
    target = presentation_anchor(agent, parent_lookup, anchors)
    return normalize_panel_key(target.tribe)


def _agent_is_starting(agent: Agent) -> bool:
    """Return whether *agent* is a transient pre-run STARTING row."""
    return agent.status == "STARTING"


def agent_is_rendered_in_agents_panel(agent: Agent) -> bool:
    """Return whether *agent* should have an Agents-tab row."""
    return not _agent_is_starting(agent)


def _panel_keys_for(agents: list[Agent]) -> list[PanelKey]:
    """Return the ordered panel keys for *agents*.

    The empty Agents tab still gets ``[None]`` as a deterministic
    empty-state focus target. Otherwise the reserved ``@default`` panel appears
    only when at least one visible agent maps to ``None`` after workflow-parent
    inheritance; all other tribe panels are sorted alphabetically by tribe
    (case-insensitive).
    """
    if not agents:
        return [None]

    rendered_agents = [a for a in agents if agent_is_rendered_in_agents_panel(a)]
    parent_lookup = _build_parent_lookup(agents)
    anchors = presentation_anchor_lookup(agents, parent_lookup)
    distinct_tribes: set[str] = set()
    has_no_tribe = False
    for a in rendered_agents:
        key = _panel_key_for_agent(a, parent_lookup, anchors)
        if key is None:
            has_no_tribe = True
        else:
            distinct_tribes.add(key)

    sorted_tribes = sorted(distinct_tribes, key=str.lower)
    if has_no_tribe:
        return [None, *sorted_tribes]
    return cast(list[PanelKey], sorted_tribes)


def effective_tribe_per_agent(agents: list[Agent]) -> list[str]:
    """Return the root-anchored display tribe for each agent in *agents*."""
    parent_lookup = _build_parent_lookup(agents)
    anchors = presentation_anchor_lookup(agents, parent_lookup)
    return [
        effective_panel_tribe(_panel_key_for_agent(a, parent_lookup, anchors))
        for a in agents
    ]


def panel_key_per_agent(
    agents: list[Agent], *, merge_tribe_panels: bool = False
) -> list[PanelKey]:
    """Return the rendered panel key for each agent in *agents*.

    In merged mode every agent belongs to the single rendered panel; callers
    that need the tribe bucket an agent would have had in split mode should use
    :func:`effective_tribe_per_agent`.
    """
    if merge_tribe_panels:
        return [None for _ in agents]
    parent_lookup = _build_parent_lookup(agents)
    anchors = presentation_anchor_lookup(agents, parent_lookup)
    return [_panel_key_for_agent(a, parent_lookup, anchors) for a in agents]


def agents_for_panel(
    agents: list[Agent],
    key: PanelKey,
    *,
    merge_tribe_panels: bool = False,
    include_hidden: bool = False,
) -> list[Agent]:
    """Return the agents whose effective panel key equals *key*."""
    candidates = (
        list(agents)
        if include_hidden
        else [a for a in agents if agent_is_rendered_in_agents_panel(a)]
    )
    if merge_tribe_panels:
        return candidates
    normalized_key = normalize_panel_key(key)
    parent_lookup = _build_parent_lookup(agents)
    anchors = presentation_anchor_lookup(agents, parent_lookup)
    return [
        a
        for a in candidates
        if _panel_key_for_agent(a, parent_lookup, anchors) == normalized_key
    ]


@dataclass
class AgentPanelGroup:
    """Mutable holder for the rendered panel order + focused panel.

    The focused panel is identified by *key*, not index, so a refresh
    that adds, removes, collapses, or expands tribe panels does not silently
    shift focus to a different panel.  In split mode ``panel_keys`` is the
    canonical base order stably partitioned with collapsed panels last.
    """

    panel_keys: list[PanelKey] = field(default_factory=lambda: [None])
    focused_idx: int = 0

    @classmethod
    def from_agents(
        cls,
        agents: list[Agent],
        focused_key: PanelKey = None,
        *,
        merge_tribe_panels: bool = False,
        collapsed_panel_keys: Collection[PanelKey] = (),
    ) -> AgentPanelGroup:
        """Build a fresh panel group from *agents*, preserving focus when possible.

        If ``focused_key`` is no longer present in the new panel set
        (e.g. its tribe's last agent was dismissed), focus falls back to
        the first available panel.  Split-panel keys retain their canonical
        order within expanded and collapsed partitions, with collapsed panels
        rendered last.
        """
        if merge_tribe_panels:
            return cls(panel_keys=[None], focused_idx=0)

        focused_key = normalize_panel_key(focused_key)
        keys = _panel_keys_for(agents)
        if collapsed_panel_keys:
            collapsed = {normalize_panel_key(key) for key in collapsed_panel_keys}
            keys = [key for key in keys if key not in collapsed] + [
                key for key in keys if key in collapsed
            ]
        try:
            idx = keys.index(focused_key)
        except ValueError:
            idx = 0
        return cls(panel_keys=keys, focused_idx=idx)

    @property
    def focused_key(self) -> PanelKey:
        if 0 <= self.focused_idx < len(self.panel_keys):
            return self.panel_keys[self.focused_idx]
        return None

    def focus_next(self, *, skip: Collection[PanelKey] = ()) -> bool:
        """Advance focus to the next panel not in *skip*, with wrap.

        Returns ``True`` when the focused index changed; ``False`` when the
        panel set is empty, holds a single panel, or every other panel is
        skipped.
        """
        return self._focus_step(1, skip)

    def focus_prev(self, *, skip: Collection[PanelKey] = ()) -> bool:
        """Retreat focus to the previous panel not in *skip*, with wrap."""
        return self._focus_step(-1, skip)

    def _focus_step(self, delta: int, skip: Collection[PanelKey]) -> bool:
        """Step focus by *delta* until a non-skipped panel is found."""
        n = len(self.panel_keys)
        if n <= 1:
            return False
        skipped = {normalize_panel_key(key) for key in skip}
        for step in range(1, n):
            idx = (self.focused_idx + delta * step) % n
            if idx == self.focused_idx:
                break
            if self.panel_keys[idx] in skipped:
                continue
            self.focused_idx = idx
            return True
        return False
