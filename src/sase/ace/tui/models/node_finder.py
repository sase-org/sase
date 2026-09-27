"""Pure Node Finder row model, filtering, hints, and text helpers.

Free of Textual imports by design; UI-adjacent helpers behind Textual
import chains are imported lazily inside the functions that need them.

Compatibility facade: the implementation lives in sibling modules
(:mod:`_node_finder_types`, :mod:`_node_finder_describe`,
:mod:`_node_finder_filter`, and :mod:`_node_finder_text`). This module
re-exports the public names so the original import path keeps working.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._node_finder_describe import (
    describe_node_finder_row,
    describe_node_finder_row_from_facts,
    kind_styles,
    node_finder_jumpable,
    node_finder_kind,
    node_finder_name,
    node_finder_title,
)
from ._node_finder_filter import filter_node_finder
from ._node_finder_text import (
    next_jumpable_index,
    node_finder_action_text,
    node_finder_glyph,
    node_finder_reason_text,
)
from ._node_finder_types import (
    NODE_FINDER_HINT_CAPACITY,
    NodeFinderReason,
    NodeFinderRole,
    NodeFinderRow,
    NodeFinderSnapshot,
    NodeFinderView,
    REASON_PRECEDENCE,
)

if TYPE_CHECKING:
    from ._node_finder_types import AgentIdentity

__all__ = [
    "NODE_FINDER_HINT_CAPACITY",
    "NodeFinderReason",
    "NodeFinderRole",
    "NodeFinderRow",
    "NodeFinderSnapshot",
    "NodeFinderView",
    "REASON_PRECEDENCE",
    "filter_node_finder",
    "next_jumpable_index",
    "node_finder_action_text",
    "node_finder_glyph",
    "node_finder_jumpable",
    "node_finder_kind",
    "node_finder_name",
    "node_finder_reason_text",
    "node_finder_title",
]
