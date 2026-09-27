"""Shared Node Finder row-model types, reasons, and capacities.

Split from :mod:`sase.ace.tui.models.node_finder`: sibling modules
(:mod:`_node_finder_describe`, :mod:`_node_finder_filter`, and
:mod:`_node_finder_text`) import these public names instead of
duplicating them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent import Agent, AgentType

    AgentIdentity = tuple[AgentType, str, str | None]


class NodeFinderReason(StrEnum):
    """Why one Node Finder row is hidden from the Agents tab."""

    FOLDED = "folded"
    BANNER = "banner"
    PANEL = "panel"
    QUERY = "query"
    NON_RUN = "non_run"


#: Most-global hider wins the single row glyph:
#: ``QUERY > NON_RUN > PANEL > BANNER > FOLDED``.
REASON_PRECEDENCE: tuple[NodeFinderReason, ...] = (
    NodeFinderReason.QUERY,
    NodeFinderReason.NON_RUN,
    NodeFinderReason.PANEL,
    NodeFinderReason.BANNER,
    NodeFinderReason.FOLDED,
)

#: Rows past this many jumpable rows carry no hint; the view flags overflow.
NODE_FINDER_HINT_CAPACITY = 62 * 62


class NodeFinderRole(StrEnum):
    """Structural role of one Node Finder row."""

    PANEL = "panel"
    GROUP = "group"
    NODE = "node"


@dataclass(frozen=True, slots=True)
class NodeFinderRow:
    """One row in the Node Finder snapshot, in tree order."""

    role: NodeFinderRole = NodeFinderRole.NODE
    identity: AgentIdentity | None = None
    agent: Agent | None = None
    name: str = ""
    title: str = ""
    kind_label: str = ""
    kind_accent: str = ""
    depth: int = 0
    panel_key: str | None = None
    parent_row: int | None = None
    jumpable: bool = False
    reasons: frozenset[NodeFinderReason] = frozenset()
    unmet_fold_count: int = 0
    nearest_collapsed: str = ""
    group_label: str = ""
    is_here: bool = False
    jumpable_count: int = 0
    hidden_count: int = 0


@dataclass(frozen=True, slots=True)
class NodeFinderSnapshot:
    """Fixed row set captured when the finder opens."""

    rows: tuple[NodeFinderRow, ...] = ()
    here_row: int | None = None
    node_count: int = 0
    hidden_count: int = 0
    query_hidden_count: int = 0
    query: str = ""
    query_incomplete: bool = False
    hidden_by_i_count: int = 0
    hint_overflow: bool = False
    focused_panel_key: str | None = None


@dataclass(frozen=True, slots=True)
class NodeFinderView:
    """One filtered projection of a snapshot, in tree order."""

    rows: tuple[NodeFinderRow, ...] = ()
    context: frozenset[int] = frozenset()
    best_index: int | None = None
    relaxed: bool = False
    hint_to_identity: dict[str, AgentIdentity] = field(default_factory=dict)
    identity_to_hint: dict[AgentIdentity, str] = field(default_factory=dict)
    overflow: bool = False
    any_match: frozenset[AgentIdentity] = frozenset()
    tokens: tuple[str, ...] = ()
    query: str = ""
