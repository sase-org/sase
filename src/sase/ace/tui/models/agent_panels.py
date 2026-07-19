"""Panel-collection model for the Agents tab.

Each Agents-tab panel renders a tag-bucket of agents.  Panels have a canonical
base order:

* The untagged panel (key ``None``) appears first only when at least one
  visible agent is effectively untagged, or when the agent list is empty.
* Tag panels are keyed by tag, sorted alphabetically (case-insensitive).
  Their order matches the order the user used to see as tag-level banners
  in the old three-level tree.

Split-panel rendering applies one additional stable partition to that base
order: expanded panels precede collapsed panels.  Both partitions retain the
canonical order, so panel layout is deterministic rather than depending on
collapse time or set iteration order.

Every structural descendant inherits its outer rendered root's effective tag,
so grouping never splits a clan or agent-family subtree across panels.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from typing import cast

from .agent import Agent
from ._agent_tree import (
    presentation_anchor,
    presentation_anchor_lookup,
    tree_parent_lookup,
)

#: Panel key type — ``None`` for the untagged panel; a tag string otherwise.
PanelKey = str | None


def _build_parent_lookup(agents: list[Agent]) -> dict[str, Agent]:
    return tree_parent_lookup(agents)


def _panel_key_for_agent(
    agent: Agent,
    parent_lookup: dict[str, Agent],
    anchors: dict[int, Agent],
) -> PanelKey:
    target = presentation_anchor(agent, parent_lookup, anchors)
    return target.tribe if target.tribe else None


def _agent_is_starting(agent: Agent) -> bool:
    """Return whether *agent* is a transient pre-run STARTING row."""
    return agent.status == "STARTING"


def agent_is_rendered_in_agents_panel(agent: Agent) -> bool:
    """Return whether *agent* should have an Agents-tab row."""
    return not _agent_is_starting(agent)


def _panel_keys_for(agents: list[Agent]) -> list[PanelKey]:
    """Return the ordered panel keys for *agents*.

    The empty Agents tab still gets ``[None]`` as a deterministic
    empty-state focus target.  Otherwise the untagged panel appears only
    when at least one visible agent maps to ``None`` after workflow-parent
    inheritance; all tag panels are sorted alphabetically by tag
    (case-insensitive).
    """
    if not agents:
        return [None]

    rendered_agents = [a for a in agents if agent_is_rendered_in_agents_panel(a)]
    parent_lookup = _build_parent_lookup(agents)
    anchors = presentation_anchor_lookup(agents, parent_lookup)
    distinct_tags: set[str] = set()
    has_untagged = False
    for a in rendered_agents:
        key = _panel_key_for_agent(a, parent_lookup, anchors)
        if key is None:
            has_untagged = True
        else:
            distinct_tags.add(key)

    sorted_tags = sorted(distinct_tags, key=str.lower)
    if has_untagged:
        return [None, *sorted_tags]
    return cast(list[PanelKey], sorted_tags)


def effective_tag_per_agent(agents: list[Agent]) -> list[PanelKey]:
    """Return the root-anchored panel key for each agent in *agents*."""
    parent_lookup = _build_parent_lookup(agents)
    anchors = presentation_anchor_lookup(agents, parent_lookup)
    return [_panel_key_for_agent(a, parent_lookup, anchors) for a in agents]


def panel_key_per_agent(
    agents: list[Agent], *, merge_tag_panels: bool = False
) -> list[PanelKey]:
    """Return the rendered panel key for each agent in *agents*.

    In merged mode every agent belongs to the single rendered panel; callers
    that need the tag bucket an agent would have had in split mode should use
    :func:`effective_tag_per_agent`.
    """
    if merge_tag_panels:
        return [None for _ in agents]
    return effective_tag_per_agent(agents)


def agents_for_panel(
    agents: list[Agent],
    key: PanelKey,
    *,
    merge_tag_panels: bool = False,
    include_hidden: bool = False,
) -> list[Agent]:
    """Return the agents whose effective panel key equals *key*."""
    candidates = (
        list(agents)
        if include_hidden
        else [a for a in agents if agent_is_rendered_in_agents_panel(a)]
    )
    if merge_tag_panels:
        return candidates
    parent_lookup = _build_parent_lookup(agents)
    anchors = presentation_anchor_lookup(agents, parent_lookup)
    return [
        a for a in candidates if _panel_key_for_agent(a, parent_lookup, anchors) == key
    ]


@dataclass
class AgentPanelGroup:
    """Mutable holder for the rendered panel order + focused panel.

    The focused panel is identified by *key*, not index, so a refresh
    that adds, removes, collapses, or expands tag panels does not silently
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
        merge_tag_panels: bool = False,
        collapsed_panel_keys: Collection[PanelKey] = (),
    ) -> AgentPanelGroup:
        """Build a fresh panel group from *agents*, preserving focus when possible.

        If ``focused_key`` is no longer present in the new panel set
        (e.g. its tag's last agent was dismissed), focus falls back to
        the first available panel.  Split-panel keys retain their canonical
        order within expanded and collapsed partitions, with collapsed panels
        rendered last.
        """
        if merge_tag_panels:
            return cls(panel_keys=[None], focused_idx=0)

        keys = _panel_keys_for(agents)
        if collapsed_panel_keys:
            collapsed = set(collapsed_panel_keys)
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

    def focus_next(self) -> bool:
        """Advance focus to the next panel with wrap.

        Returns ``True`` when the focused index changed; ``False`` when
        the panel set is empty or contains a single panel.
        """
        n = len(self.panel_keys)
        if n <= 1:
            return False
        new_idx = (self.focused_idx + 1) % n
        if new_idx == self.focused_idx:
            return False
        self.focused_idx = new_idx
        return True

    def focus_prev(self) -> bool:
        """Retreat focus to the previous panel with wrap.

        Returns ``True`` when the focused index changed; ``False`` when
        the panel set is empty or contains a single panel.
        """
        n = len(self.panel_keys)
        if n <= 1:
            return False
        new_idx = (self.focused_idx - 1) % n
        if new_idx == self.focused_idx:
            return False
        self.focused_idx = new_idx
        return True
