"""Panel-collection model for the Agents tab.

Each Agents-tab panel renders a tag-bucket of agents:

* The first panel (``focused_idx`` 0, key ``None``) is the "untagged" main
  pane.
* Subsequent panels are keyed by tag, sorted alphabetically (case-
  insensitive).  Their order matches the order the user used to see as
  tag-level banners in the old three-level tree.

Rendered workflow children inherit their parent's tag so they appear in the
parent's panel even if the child has no tag of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .agent import Agent

#: Panel key type — ``None`` for the untagged main panel; a tag string
#: otherwise.
PanelKey = str | None


def _build_parent_lookup(agents: list[Agent]) -> dict[str, Agent]:
    return {
        a.raw_suffix: a
        for a in agents
        if a.raw_suffix and not a.is_rendered_workflow_child
    }


def _panel_key_for_agent(agent: Agent, parent_lookup: dict[str, Agent]) -> PanelKey:
    target = agent
    if agent.is_rendered_workflow_child and agent.parent_timestamp:
        parent = parent_lookup.get(agent.parent_timestamp)
        if parent is not None:
            target = parent
    return target.tag if target.tag else None


def _panel_keys_for(agents: list[Agent]) -> list[PanelKey]:
    """Return the ordered panel keys for *agents*: ``[None, tag1, tag2, ...]``.

    Tag panels follow the untagged main panel and are sorted
    alphabetically by tag (case-insensitive).  The untagged panel always
    appears first, even when every loaded agent is tagged — it is the
    fallback focus target when a tag's panel disappears mid-session.
    """
    parent_lookup = _build_parent_lookup(agents)
    distinct_tags: set[str] = set()
    for a in agents:
        key = _panel_key_for_agent(a, parent_lookup)
        if key is not None:
            distinct_tags.add(key)
    return [None, *sorted(distinct_tags, key=str.lower)]


def panel_key_per_agent(agents: list[Agent]) -> list[PanelKey]:
    """Return the panel key (with parent inheritance) for each agent in *agents*."""
    parent_lookup = _build_parent_lookup(agents)
    return [_panel_key_for_agent(a, parent_lookup) for a in agents]


def agents_for_panel(agents: list[Agent], key: PanelKey) -> list[Agent]:
    """Return the agents whose effective panel key equals *key*."""
    parent_lookup = _build_parent_lookup(agents)
    return [a for a in agents if _panel_key_for_agent(a, parent_lookup) == key]


@dataclass
class AgentPanelGroup:
    """Mutable holder for the panel set + focused panel.

    The focused panel is identified by *key*, not index, so a refresh
    that adds or removes tag panels does not silently shift focus to a
    different panel.
    """

    panel_keys: list[PanelKey] = field(default_factory=lambda: [None])
    focused_idx: int = 0

    @classmethod
    def from_agents(
        cls,
        agents: list[Agent],
        focused_key: PanelKey = None,
    ) -> AgentPanelGroup:
        """Build a fresh panel group from *agents*, preserving focus when possible.

        If ``focused_key`` is no longer present in the new panel set
        (e.g. its tag's last agent was dismissed), focus falls back to
        the untagged main pane.
        """
        keys = _panel_keys_for(agents)
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
