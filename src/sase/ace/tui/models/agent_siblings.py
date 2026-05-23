"""Visible sibling index for Agents-tab rows."""

from __future__ import annotations

from dataclasses import dataclass, field

from .agent import Agent
from .agent_panels import agent_is_rendered_in_agents_panel


def agent_sibling_family(agent: Agent) -> str | None:
    """Return the case-folded sibling family key for ``agent``.

    Sibling navigation is based only on the explicit ``Agent.agent_name``.
    Dotless names and names with an empty first or second segment do not have a
    sibling family.
    """
    name = agent.agent_name
    if not name or "." not in name:
        return None
    family, rest = name.split(".", 1)
    if not family or not rest:
        return None
    return family.casefold()


@dataclass(frozen=True)
class AgentSiblingRow:
    """One visible Agents-tab row used to build a sibling index."""

    global_idx: int
    panel_idx: int
    agent: Agent
    family: str | None = None


@dataclass(frozen=True)
class AgentSiblingIndex:
    """Render-order sibling lookup for currently visible Agents-tab rows."""

    _siblings_by_global_idx: dict[int, tuple[int, ...]] = field(default_factory=dict)
    _panel_idx_by_global_idx: dict[int, int] = field(default_factory=dict)

    @classmethod
    def from_visible_rows(cls, rows: list[AgentSiblingRow]) -> AgentSiblingIndex:
        """Build an index from visible rows in actual render order."""
        panel_idx_by_global_idx: dict[int, int] = {}
        family_by_global_idx: dict[int, str] = {}
        members_by_family: dict[str, list[int]] = {}

        for row in rows:
            panel_idx_by_global_idx[row.global_idx] = row.panel_idx
            if not agent_is_rendered_in_agents_panel(row.agent):
                continue
            family = (
                row.family
                if row.family is not None
                else agent_sibling_family(row.agent)
            )
            if family is None:
                continue
            family_by_global_idx[row.global_idx] = family
            members_by_family.setdefault(family, []).append(row.global_idx)

        siblings_by_global_idx: dict[int, tuple[int, ...]] = {}
        for global_idx, family in family_by_global_idx.items():
            siblings_by_global_idx[global_idx] = tuple(
                idx for idx in members_by_family[family] if idx != global_idx
            )

        return cls(
            _siblings_by_global_idx=siblings_by_global_idx,
            _panel_idx_by_global_idx=panel_idx_by_global_idx,
        )

    def siblings_for(self, global_idx: int) -> tuple[int, ...]:
        """Return visible sibling global indices for ``global_idx``."""
        return self._siblings_by_global_idx.get(global_idx, ())

    def sibling_count(self, global_idx: int) -> int:
        """Return the number of visible siblings for ``global_idx``."""
        return len(self.siblings_for(global_idx))

    def panel_idx_for(self, global_idx: int) -> int | None:
        """Return the rendered panel index containing ``global_idx``."""
        return self._panel_idx_by_global_idx.get(global_idx)
