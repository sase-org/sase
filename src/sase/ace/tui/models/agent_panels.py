"""Panel-collection model for the Agents tab.

Each Agents-tab panel renders a tag-bucket of agents:

* The first panel (``focused_idx`` 0, key ``None``) is the "untagged" main
  pane.
* Subsequent panels are keyed by tag, sorted alphabetically (case-
  insensitive).  Their order matches the order the user used to see as
  tag-level banners in the old three-level tree.

Workflow children inherit their parent's tag so they appear in the
parent's panel even if the child has no tag of its own.

Also defines top-level Agents-tab panel slots (LIST / CHAT / FILE) and
the four cyclable layouts (CLASSIC / TRIPTYCH / STACK / FOCUS) that
arrange them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .agent import Agent


class AgentsLayout(Enum):
    """Top-level geometry for the Agents-tab panels.

    Members are ordered as the cycle that ``p`` walks; ``P`` walks them
    in reverse.
    """

    CLASSIC = "classic"
    TRIPTYCH = "triptych"
    STACK = "stack"
    FOCUS = "focus"


class PanelSlot(Enum):
    """Logical content rendered in an Agents-tab panel slot.

    The Agents tab has three slots; rotation reassigns which logical
    content occupies each slot, so ``{`` / ``}`` work uniformly across
    layouts.
    """

    LIST = "list"
    CHAT = "chat"
    FILE = "file"


_DEFAULT_PANEL_ORDER: tuple[PanelSlot, PanelSlot, PanelSlot] = (
    PanelSlot.LIST,
    PanelSlot.CHAT,
    PanelSlot.FILE,
)


_LAYOUT_CYCLE: tuple[AgentsLayout, ...] = (
    AgentsLayout.CLASSIC,
    AgentsLayout.TRIPTYCH,
    AgentsLayout.STACK,
    AgentsLayout.FOCUS,
)


@dataclass
class AgentsLayoutState:
    """Mutable layout + panel-rotation state for the Agents tab.

    ``layout`` controls geometry (cycled with ``p`` / ``P``).
    ``order`` is a permutation of ``(LIST, CHAT, FILE)`` that names which
    logical content sits in each slot — slot 1 is "primary" (largest,
    focus border, the only one visible in FOCUS).  Rotation (``{`` /
    ``}``) is a cyclic shift over this triple.

    State is *not* persisted across TUI restarts; it resets to the
    defaults (CLASSIC, ``[LIST, CHAT, FILE]``) every cold start.
    """

    layout: AgentsLayout = AgentsLayout.CLASSIC
    order: tuple[PanelSlot, PanelSlot, PanelSlot] = _DEFAULT_PANEL_ORDER

    def cycle_layout(self, *, reverse: bool = False) -> AgentsLayout:
        """Advance to the next (or previous) layout and return it."""
        idx = _LAYOUT_CYCLE.index(self.layout)
        step = -1 if reverse else 1
        self.layout = _LAYOUT_CYCLE[(idx + step) % len(_LAYOUT_CYCLE)]
        return self.layout

    def rotate(self, *, reverse: bool = False) -> tuple[PanelSlot, ...]:
        """Cyclic-shift the panel order and return the new tuple.

        Forward rotation moves the previous primary to the end:
        ``[L, C, F] -> [C, F, L] -> [F, L, C] -> [L, C, F]``.  Reverse
        does the opposite.  Three presses returns to the starting order.
        """
        if reverse:
            self.order = (self.order[-1], *self.order[:-1])
        else:
            self.order = (*self.order[1:], self.order[0])
        return self.order

    def slot_for_position(self, position: int) -> PanelSlot:
        """Return the logical panel sitting at slot index *position* (1-based)."""
        if not 1 <= position <= 3:
            raise ValueError(f"position must be 1, 2, or 3 (got {position})")
        return self.order[position - 1]

    def position_for_slot(self, slot: PanelSlot) -> int:
        """Return the 1-based position currently occupied by *slot*."""
        return self.order.index(slot) + 1

    @property
    def primary(self) -> PanelSlot:
        """The logical panel currently in slot #1 ("primary")."""
        return self.order[0]


#: Panel key type — ``None`` for the untagged main panel; a tag string
#: otherwise.
PanelKey = str | None


def _build_parent_lookup(agents: list[Agent]) -> dict[str, Agent]:
    return {a.raw_suffix: a for a in agents if a.raw_suffix and not a.is_workflow_child}


def _panel_key_for_agent(agent: Agent, parent_lookup: dict[str, Agent]) -> PanelKey:
    target = agent
    if agent.is_workflow_child and agent.parent_timestamp:
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
